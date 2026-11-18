"""Find past decisions similar to a described incident, and the articles of the rules.

Three methods, and one rule each for decisions and for articles.

    bm25     documents that share words with the question
    vector   documents whose meaning is close to the question's
    hybrid   both of the above, combined by reciprocal rank fusion (RRF)

Decisions: a question that belongs to an event is answered only from decisions of
EARLIER events. The stewards of that weekend could not read their own later decisions,
and in the evaluation the question's own decision must never come back as a result.

Articles: only the issue of each rule book that was in force on the event's date. The
Sporting Regulations were changed five times during the 2026 season.

Articles can also be reached through past decisions. Every decision names the articles
it was decided under, so the articles cited by the decisions found for a question are
added after the k articles found by search:

    question ──▶ decision search ──▶ 5 decisions ──▶ the articles they cite ──┐
        └──────▶ rule search ──────▶ 8 articles ─────────────────────────────┴──▶ both, no repeats

Search alone misses the general articles that the stewards cite most (Appendix L IV.2 on
collisions, ISC 12.2.1 on instructions); the decisions name them (PLAN.md, step 3).

RRF looks only at ranks, never at scores. A document ranked 1st by BM25 and 3rd by the
vector search gets w_bm25/(60+1) + w_vector/(60+3); the two weights add up to 1. BM25 scores and vector distances are on
different scales and cannot be added; ranks can.
"""

from langchain_chroma import Chroma
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from . import config, index, manifest

METHODS = ("bm25", "vector", "hybrid")


def check_method(method: str) -> None:
    if method not in METHODS:
        raise ValueError(f"Unknown method {method!r}. Choose one of {', '.join(METHODS)}.")


def holding(cited: str, ids_in_issue: set[str]) -> set[str]:
    """The articles of one issue whose text holds a cited article.

    The stewards cite down to a point ("ISC-L:IV.2.d"); the rules are cut at numbered
    paragraphs ("ISC-L:IV.2", whose text holds points a) to e)). So a citation is held by:
    the article with the same id; else its nearest parent; else, when the citation is
    broader than the paragraphs ("F1-B:5.11"), every article under it. Empty: not found.
    """
    if cited in ids_in_issue:
        return {cited}
    book, number = cited.split(":")
    parts = number.split(".")
    for end in range(len(parts) - 1, 0, -1):
        parent = f"{book}:{'.'.join(parts[:end])}"
        if parent in ids_in_issue:
            return {parent}
    return {i for i in ids_in_issue if i.startswith(cited + ".")}


def _retrieve(
    question: str,
    method: str,
    bm25: BM25Retriever,
    store: Chroma | None,
    where: dict,
    k: int,
    id_key: str,
) -> list[Document]:
    """Run one method. `where` is the Chroma filter that does what the BM25 index was cut for."""
    check_method(method)
    if method != "bm25" and store is None:
        raise ValueError(f"The {method} method needs the vector index. Run `f1aisteward build --index` first.")

    def vector(n: int):
        return store.as_retriever(search_kwargs={"k": n, "filter": where})

    if method == "bm25":
        bm25.k = k
        return bm25.invoke(question)
    if method == "vector":
        return vector(k).invoke(question)
    bm25.k = config.CANDIDATES
    fusion = EnsembleRetriever(
        retrievers=[bm25, vector(config.CANDIDATES)],
        weights=[1 - config.VECTOR_WEIGHT, config.VECTOR_WEIGHT],
        # Two documents can have the same text (two decisions about one incident, or an
        # article that did not change between issues). Without id_key the fusion treats
        # equal text as one document and drops the rest.
        id_key=id_key,
    )
    return fusion.invoke(question)[:k]


class DecisionSearch:
    def __init__(self, records: list[dict], vector_store: Chroma | None = None) -> None:
        """`vector_store` may be left out; then only the "bm25" method works."""
        self.records = records
        self.by_id = {record["id"]: record for record in records}
        self.vector_store = vector_store
        self.after_last_round = max((record["round"] for record in records), default=0) + 1
        self._bm25: dict[int, BM25Retriever | None] = {}

    def search(
        self,
        question: str,
        before_round: int | None = None,
        method: str = config.SEARCH_METHOD,
        k: int = config.TOP_K,
    ) -> list[dict]:
        """The k most similar decisions from rounds earlier than `before_round`, best first.

        Without `before_round` every decision is searched. The result is a list of the
        parsed records, and it is empty when no earlier decision exists.
        """
        if before_round is None:
            before_round = self.after_last_round
        bm25 = self._bm25_before(before_round)
        if bm25 is None:  # the first event of the season: nothing came before it
            check_method(method)
            return []
        # Chroma stores the round next to each vector and filters on it while searching.
        where = {"round": {"$lt": before_round}}
        documents = _retrieve(question, method, bm25, self.vector_store, where, k, id_key="id")
        return [self._record(document.metadata["id"]) for document in documents]

    def _bm25_before(self, before_round: int) -> BM25Retriever | None:
        """BM25 has no metadata filter, so there is one small index per cut-off round.

        Building one takes milliseconds. Each index also counts how rare a word is over
        the earlier decisions only, so nothing about later events leaks into the scores.
        """
        if before_round not in self._bm25:
            earlier = [record for record in self.records if record["round"] < before_round]
            self._bm25[before_round] = index.bm25_retriever(earlier)
        return self._bm25[before_round]

    def _record(self, decision_id: str) -> dict:
        if decision_id not in self.by_id:
            raise ValueError(
                f"The vector index holds {decision_id}, which is not in the parsed decisions. "
                "Run `f1aisteward build --index` again."
            )
        return self.by_id[decision_id]


class RuleSearch:
    def __init__(self, articles: list[dict], regulations: dict, vector_store: Chroma | None = None) -> None:
        """`articles` are every issue's articles; `regulations` says which issue is in force when."""
        self.articles = articles
        self.by_key = {article["key"]: article for article in articles}
        self.ids_in: dict[str, set[str]] = {}  # issue -> the article ids it holds
        # (issue, article id) -> its articles; two when the FIA numbered two paragraphs alike
        self.in_issue: dict[tuple[str, str], list[dict]] = {}
        self.book_of = {issue["id"]: issue["book"] for issue in regulations["issues"]}
        for article in articles:
            self.ids_in.setdefault(article["issue"], set()).add(article["id"])
            self.in_issue.setdefault((article["issue"], article["id"]), []).append(article)
        self.regulations = regulations
        self.vector_store = vector_store
        self._bm25: dict[tuple[str, ...], BM25Retriever | None] = {}

    def issues_on(self, date: str | None) -> list[str]:
        """The issue of each book in force on `date`; without a date, the latest ones."""
        return manifest.issues_in_force(self.regulations, date or "9999-12-31")

    def search(
        self,
        question: str,
        date: str | None = None,
        method: str = config.RULES_SEARCH_METHOD,
        k: int = config.TOP_K_RULES,
        decisions: list[dict] | None = None,
    ) -> list[dict]:
        """The k articles closest to the question, from the issues in force on `date`, best first.

        When `decisions` are given (the past decisions found for the same question), the
        articles they cite follow, unless search already found them. The result is then
        longer than k.
        """
        found = self.closest(question, date, method, k)
        if decisions:
            shown = {article["key"] for article in found}
            found += [article for article in self.cited_by(decisions, date) if article["key"] not in shown]
        return found

    def cited_by(self, decisions: list[dict], date: str | None = None) -> list[dict]:
        """The articles these decisions cite, as they read in the issues in force on `date`.

        A decision of May cites the rule of May; a question of November gets the article of
        the same number from the November issue. A citation of a book that is not included
        (Section C), or of a number the issue does not have, adds nothing.
        """
        issue_of = {self.book_of[issue]: issue for issue in self.issues_on(date)}
        found: dict[str, dict] = {}
        for decision in decisions:
            for cited in decision["articles"]:
                issue = issue_of.get(cited.split(":")[0])
                if issue is None:
                    continue
                for article_id in sorted(holding(cited, self.ids_in.get(issue, set()))):
                    for article in self.in_issue[(issue, article_id)]:
                        found.setdefault(article["key"], article)
        return list(found.values())

    def closest(self, question: str, date: str | None, method: str, k: int) -> list[dict]:
        """Search alone: the k articles closest to the question, in the issues in force on `date`."""
        issues = tuple(sorted(self.issues_on(date)))
        if issues not in self._bm25:  # like decisions: one small BM25 index per set of issues
            self._bm25[issues] = index.bm25_over(
                [index.rule_document(a) for a in self.articles if a["issue"] in issues], k
            )
        bm25 = self._bm25[issues]
        if bm25 is None:
            check_method(method)
            return []
        where = {"issue": {"$in": list(issues)}}
        documents = _retrieve(question, method, bm25, self.vector_store, where, k, id_key="key")
        missing = [d.metadata["key"] for d in documents if d.metadata["key"] not in self.by_key]
        if missing:
            raise ValueError(
                f"The vector index holds {missing[0]}, which is not in the parsed rules. "
                "Run `f1aisteward build --index` again."
            )
        return [self.by_key[document.metadata["key"]] for document in documents]
