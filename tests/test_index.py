"""Decisions become searchable documents: the right text, plain metadata, sensible words."""

from search_data import RECORDS, WordCountEmbeddings, decision

from f1aisteward import index


def test_the_searched_text_is_the_session_and_what_happened():
    assert index.chunk_text(RECORDS[0]) == "Race. Car 7 pushed Car 8 wide at turn 3."
    assert index.chunk_text(decision(1, 9, "Car 7 was late.", session=None)) == "Car 7 was late."


def test_the_answer_is_in_metadata_and_not_in_the_searched_text():
    document = index.to_document(RECORDS[1])

    assert document.metadata["articles"] == "F1-B:4.5.6"
    assert document.metadata["penalty"] == "time_penalty"
    assert document.metadata["round"] == 1
    assert "F1-B" not in document.page_content and "penalty" not in document.page_content
    # Chroma stores only plain values.
    assert all(isinstance(value, str | int) for value in document.metadata.values())


def test_words_are_lower_case_and_without_punctuation():
    assert index.tokenize("Car 7, at Turn 3.") == ["car", "7", "at", "turn", "3"]
    assert index.tokenize("car 7 at turn 3") == index.tokenize("Car 7 at Turn 3.")


def test_bm25_matches_whatever_the_capitals_and_full_stops():
    retriever = index.bm25_retriever(RECORDS, k=1)
    [best] = retriever.invoke("SPEED LIMIT in the PIT LANE.")
    assert best.metadata["id"] == "2031-round2-003"


def test_bm25_over_no_decisions_is_none_and_not_an_error():
    assert index.bm25_retriever([]) is None


def test_the_vector_index_is_written_to_disk_and_read_back(tmp_path):
    index.build_vector_store(RECORDS, WordCountEmbeddings(), directory=tmp_path)

    store = index.open_vector_store(WordCountEmbeddings(), directory=tmp_path)
    assert index.count(store) == len(RECORDS)
    [best] = store.similarity_search("pit lane speed limit", k=1)
    assert best.metadata["id"] == "2031-round2-003"


def test_building_again_replaces_the_index(tmp_path):
    index.build_vector_store(RECORDS, WordCountEmbeddings(), directory=tmp_path)
    store = index.build_vector_store(RECORDS[:2], WordCountEmbeddings(), directory=tmp_path)
    assert index.count(store) == 2


def test_a_question_is_embedded_once_however_often_it_is_searched():
    model = WordCountEmbeddings()
    remembered = index.RememberedQuestions(model)

    remembered.warm(["first question", "second question", "first question"])
    assert model.requests == 1  # one request for all of them
    assert remembered.embed_query("first question") == model._vector("first question")
    remembered.embed_query("second question")
    assert model.requests == 1  # and none after that

    remembered.embed_query("a new question")
    assert model.requests == 2


def test_an_article_is_searched_with_its_heading_path_and_filtered_by_its_issue():
    from search_data import RULE_ARTICLES

    document = index.rule_document(RULE_ARTICLES[4])
    assert document.page_content.startswith("CHAPTER IV - CODE OF CONDUCT > 2. Overtaking > ISC-L:IV.2\na) A car")
    assert document.metadata == {"key": "L-01/ISC-L:IV.2", "id": "ISC-L:IV.2", "book": "ISC-L", "issue": "L-01"}


def test_an_article_that_did_not_change_is_stored_once_per_issue(tmp_path):
    from search_data import RULE_ARTICLES

    store = index.build_rule_store(RULE_ARTICLES, WordCountEmbeddings(), directory=tmp_path)
    assert index.count(store) == len(RULE_ARTICLES)
