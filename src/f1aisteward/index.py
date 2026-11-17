"""Turn parsed decisions and rule articles into the indexes search needs.

    one decision  ->  one Document: the text that is searched, plus metadata
    one article   ->  one Document, in a second collection (`rules`)
                          |
            +-------------+--------------+
            |                            |
       BM25 index                   vector index
       counts words                 one vector per decision, made by an embedding model
       built in memory,             stored in Chroma under .cache/index/,
       in milliseconds              built once by `build --index` (calls OpenAI)

Both indexes hold the same Documents. Only the way they are looked up differs.
"""

import json
import re
from pathlib import Path

from chromadb.config import Settings
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from . import config
from .parse import rules


def load_decisions(path: Path = config.PARSED_DECISIONS) -> list[dict]:
    """The records `build --decisions` wrote, one per decision."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def chunk_text(record: dict) -> str:
    """The text of a decision that is searched: the session and what happened.

    A question is also "what happened", so like is compared with like. The article and
    the penalty are left out on purpose: they are the answer, and they stay in metadata.
    """
    return f"{record['session']}. {record['fact']}" if record["session"] else record["fact"]


def to_document(record: dict) -> Document:
    """Chroma accepts only plain values in metadata, so the list of articles becomes one string."""
    return Document(
        page_content=chunk_text(record),
        metadata={
            "id": record["id"],
            "event": record["event"],
            "round": record["round"],  # search filters on this: "earlier events only"
            "date": record["date"],
            "kind": record["kind"],
            "articles": ", ".join(record["articles"]),
            "penalty": record["penalty"]["type"],
        },
    )


def rule_document(article: dict) -> Document:
    """An article of the rules. `issue` is what search filters on: "the rules in force then"."""
    return Document(
        page_content=rules.chunk_text(article),
        metadata={"key": article["key"], "id": article["id"], "book": article["book"], "issue": article["issue"]},
    )


# ---------------------------------------------------------------- BM25


def tokenize(text: str) -> list[str]:
    """Split text into the words BM25 counts: lower case, no punctuation.

    LangChain's default is `text.split()`, which keeps "Car", "car" and "car." apart as
    three different words. A question typed in lower case would then miss most decisions.
    """
    return re.findall(r"[a-z0-9]+", text.lower())


def bm25_retriever(records: list[dict], k: int = config.TOP_K) -> BM25Retriever | None:
    """A keyword search over exactly these decisions, or None when there are none.

    BM25 scores a decision by the words it shares with the question. A word counts for
    more when few decisions contain it ("unsafe" says more than "car").
    """
    return bm25_over([to_document(r) for r in records], k)


def bm25_over(documents: list[Document], k: int) -> BM25Retriever | None:
    """A keyword search over these documents, or None when there are none."""
    if not documents:  # BM25Retriever raises an error on an empty list
        return None
    return BM25Retriever.from_documents(documents, preprocess_func=tokenize, k=k)


# ---------------------------------------------------------------- vectors


def openai_embeddings() -> Embeddings:
    """The embedding model. It reads OPENAI_API_KEY from the environment."""
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=config.EMBEDDING_MODEL)


class RememberedQuestions(Embeddings):
    """An embedding model that never asks twice for the vector of the same question.

    The evaluation searches with each question several times (vector, then hybrid).
    `warm` fetches the vectors of all questions in one request; after that the
    searches cost no further requests.
    """

    def __init__(self, model: Embeddings) -> None:
        self.model = model
        self.vectors: dict[str, list[float]] = {}

    def warm(self, texts: list[str]) -> None:
        new = [text for text in dict.fromkeys(texts) if text not in self.vectors]
        if new:
            self.vectors.update(zip(new, self.model.embed_documents(new)))

    def embed_query(self, text: str) -> list[float]:
        self.warm([text])
        return self.vectors[text]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.embed_documents(texts)


def open_vector_store(
    embeddings: Embeddings, directory: Path = config.INDEX_DIR, collection: str = config.DECISIONS_COLLECTION
) -> Chroma:
    """A Chroma collection in `directory`: decisions unless told otherwise. Empty until built."""
    return Chroma(
        collection_name=collection,
        embedding_function=embeddings,
        persist_directory=str(directory),
        client_settings=Settings(anonymized_telemetry=False),  # Chroma must not phone home
    )


def build_vector_store(records: list[dict], embeddings: Embeddings, directory: Path = config.INDEX_DIR) -> Chroma:
    """Embed every decision and store it, replacing whatever the collection held before."""
    store = open_vector_store(embeddings, directory)
    store.reset_collection()
    store.add_documents([to_document(r) for r in records], ids=[r["id"] for r in records])
    return store


def build_rule_store(articles: list[dict], embeddings: Embeddings, directory: Path = config.INDEX_DIR) -> Chroma:
    """Embed every article of every issue and store it, replacing the collection's old contents.

    An article that did not change between two issues is stored once per issue, so that
    filtering on the issue in force always finds the whole text of that issue.
    """
    store = open_vector_store(embeddings, directory, config.RULES_COLLECTION)
    store.reset_collection()
    store.add_documents([rule_document(a) for a in articles], ids=[a["key"] for a in articles])
    return store


def count(store: Chroma) -> int:
    """How many documents the collection holds."""
    return len(store.get(include=[])["ids"])
