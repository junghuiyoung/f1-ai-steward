"""Made-up decisions and a stand-in embedding model for the search tests.

No FIA text and no network: the "embedding" here is a word count, computed locally.
"""

import zlib

from langchain_core.embeddings import Embeddings

from f1aisteward import index

DATES = {1: "2031-03-01", 2: "2031-07-01", 3: "2031-09-01"}


def decision(round_number, number, fact, articles=("F1-B:1.2.3",), session="Race", layout="single_car"):
    return {
        "id": f"2031-round{round_number}-{number:03d}",
        "event": f"round{round_number}",
        "round": round_number,
        "date": DATES[round_number],
        "number": number,
        "layout": layout,
        "session": session,
        "fact": fact,
        "articles": list(articles),
        "penalty": {"type": "time_penalty", "value": 5, "unit": "s"},
        "kind": "judgment_incident",
    }


# Three events. Every event has a collision and a pit lane decision, so a question
# from any event has a tempting match inside its own event and in later ones.
RECORDS = [
    decision(1, 1, "Car 7 pushed Car 8 wide at turn 3."),
    decision(1, 2, "Car 4 was released from its pit box into the path of Car 9.", ["F1-B:4.5.6"]),
    decision(2, 1, "Car 7 pushed Car 8 wide at turn 3."),
    decision(2, 2, "Car 5 was released from its pit box into the path of Car 2.", ["F1-B:4.5.6"]),
    decision(2, 3, "Car 6 drove faster than the pit lane speed limit.", ["F1-B:7.8.9"], session="Qualifying"),
    decision(3, 1, "Car 7 pushed Car 8 wide at turn 3."),
    decision(3, 2, "Car 3 was released from its pit box into the path of Car 1.", ["F1-B:4.5.6"]),
]


class WordCountEmbeddings(Embeddings):
    """Texts that share words get vectors that point the same way. Good enough to test with."""

    def __init__(self):
        self.requests = 0  # how many times the "model" was called

    def embed_documents(self, texts):
        self.requests += 1
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self.embed_documents([text])[0]

    def _vector(self, text):
        vector = [0.0] * 64
        for word in index.tokenize(text):
            vector[zlib.crc32(word.encode()) % 64] += 1.0
        length = sum(x * x for x in vector) ** 0.5 or 1.0
        return [x / length for x in vector]


# Made-up rule documents: one book with two issues, and one appendix with one.
REGULATIONS = {
    "issues": [
        {"id": "B-01", "book": "F1-B", "in_force_from": "2031-01-01"},
        {"id": "B-02", "book": "F1-B", "in_force_from": "2031-06-01"},
        {"id": "L-01", "book": "ISC-L", "in_force_from": "2031-02-01"},
    ]
}


def article(issue, article_id, text, headings=("ARTICLE B1: MADE-UP RULES",)):
    return {
        "key": f"{issue}/{article_id}",
        "id": article_id,
        "book": article_id.split(":")[0],
        "issue": issue,
        "headings": list(headings),
        "text": text,
    }


RULE_ARTICLES = [
    article("B-01", "F1-B:7.8.9", "B7.8.9 Cars must not exceed the pit lane speed limit."),
    article("B-01", "F1-B:4.5.6", "B4.5.6 A car must not be released from its pit box into the path of another."),
    # issue 2 keeps 7.8.9 word for word and rewrites 4.5.6
    article("B-02", "F1-B:7.8.9", "B7.8.9 Cars must not exceed the pit lane speed limit."),
    article("B-02", "F1-B:4.5.6", "B4.5.6 A car released unsafely from its pit box will be reported."),
    article(
        "L-01",
        "ISC-L:IV.2",
        "a) A car alone may use the whole track.\nd) Pushing another car wide or hitting it will be reported.",
        headings=("CHAPTER IV - CODE OF CONDUCT", "2. Overtaking"),
    ),
]
