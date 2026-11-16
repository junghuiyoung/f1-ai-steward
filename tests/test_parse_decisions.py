"""The decision parser cuts a document into its fields, whatever the stewards typed around them."""

from decision_text import SINGLE_CAR_FIELDS, form, replaced, without

from f1aisteward.parse import decisions


def test_parse_reads_the_eight_fields():
    parsed = decisions.parse(form(SINGLE_CAR_FIELDS))

    assert parsed.layout == "single_car"
    assert parsed.document == 12
    assert parsed.cars == [7]
    assert parsed.driver == "Ada Example"
    assert parsed.competitor == "Northwind Racing"
    assert parsed.session == "Race"
    assert parsed.fact == "Car 7 pushed Car 8 wide at turn 3."
    assert parsed.infringement == "Breach of Article B1.2.3 of the Example Regulations."
    assert parsed.decision == "5 second time penalty."
    assert parsed.missing == []
    assert parsed.notes == []


def test_time_is_the_time_of_the_incident_not_of_the_document():
    # The header says "Time 17:05" (document issued); the field says "Time 15:36".
    assert decisions.parse(form(SINGLE_CAR_FIELDS)).time == "15:36"


def test_wrapped_lines_are_joined_and_values_use_ordinary_spaces():
    parsed = decisions.parse(form(SINGLE_CAR_FIELDS))
    assert parsed.reason == "The Stewards watched the video and found that Car 7 left no room for Car 8."
    assert " " not in parsed.reason


def test_the_signature_label_of_a_second_page_is_not_part_of_the_reason():
    # The Reason runs over a page break. The text of page 2 starts with the label that is
    # printed under the signatures.
    reason = ["The Stewards watched the video and found that", "The Stewards", "Car 7 left no room for Car 8."]
    parsed = decisions.parse(form(replaced(SINGLE_CAR_FIELDS, "Reason", reason)))
    assert parsed.reason == "The Stewards watched the video and found that Car 7 left no room for Car 8."


def test_closing_paragraphs_are_not_part_of_the_reason():
    reason = decisions.parse(form(SINGLE_CAR_FIELDS)).reason
    assert "reminded" not in reason
    assert "Sam Sample" not in reason


def test_a_wrapped_line_that_starts_with_a_field_name_is_not_a_field():
    # Inside a value the words are joined by non-breaking spaces, so "Infringement was ..."
    # at the start of a wrapped line of the Fact is text, not the Infringement field.
    fields = replaced(SINGLE_CAR_FIELDS, "Fact", ["Car 7 slowed on the straight. No", "Infringement was seen by the marshals."])
    parsed = decisions.parse(form(fields))

    assert parsed.fact == "Car 7 slowed on the straight. No Infringement was seen by the marshals."
    assert parsed.infringement == "Breach of Article B1.2.3 of the Example Regulations."


def test_decision_field_can_run_over_two_lines():
    fields = replaced(SINGLE_CAR_FIELDS, "Decision", ["5 second time penalty.", "(5 seconds added to the race time)."])
    assert decisions.parse(form(fields)).decision == "5 second time penalty. (5 seconds added to the race time)."


def test_missing_reason_label_splits_the_decision_after_its_first_sentence():
    fields = without(SINGLE_CAR_FIELDS, "Reason")
    fields = replaced(fields, "Decision", ["Required to start from the pit lane.", "The team changed the car overnight,", "which the rules do not allow."])
    parsed = decisions.parse(form(fields))

    assert parsed.decision == "Required to start from the pit lane."
    assert parsed.reason == "The team changed the car overnight, which the rules do not allow."
    assert parsed.notes  # the workaround is recorded


def test_missing_reason_label_keeps_a_bracketed_second_line_with_the_decision():
    fields = without(SINGLE_CAR_FIELDS, "Reason")
    fields = replaced(fields, "Decision", ["5 second time penalty.", "(5 seconds added to the race time)."])
    parsed = decisions.parse(form(fields))

    assert parsed.decision == "5 second time penalty. (5 seconds added to the race time)."
    assert parsed.reason is None


def test_a_missing_required_field_is_reported_not_raised():
    parsed = decisions.parse(form(without(SINGLE_CAR_FIELDS, "Infringement")))
    assert parsed.missing == ["infringement"]


def test_a_decision_without_a_session_is_still_a_decision():
    # Something that happened off the track, such as arriving late for a press conference.
    parsed = decisions.parse(form(without(SINGLE_CAR_FIELDS, "Session")))
    assert parsed.session is None
    assert parsed.missing == []


def test_driver_field_in_an_unexpected_shape_is_kept_and_noted():
    parsed = decisions.parse(form(replaced(SINGLE_CAR_FIELDS, "No / Driver", "Ada Example")))
    assert parsed.driver == "Ada Example"
    assert parsed.cars == []
    assert parsed.notes


# The second layout: a cover page, then a decision about several cars listed in a table.
# That attachment is made by other software and uses ordinary spaces everywhere.
CAR_TABLE = """2031 EXAMPLE GRAND PRIX
From The Stewards
To All Teams
Document 30
Date 01 June 2031
Time 19:46
Title Decision - Slow laps
Enclosed slow laps.pdf
Sam Sample Robin Placeholder

2031 EXAMPLE GRAND PRIX
From The Stewards      Document 30
        Time  19:46

The Stewards have looked at the following matter:

Session Qualifying

Fact The cars below were slower than the time limit on their out lap.

No. Car Driver Competitor Time of Day Lap
1 7 Ada Example Northwind Racing 16:04:59 L4
2 21 Bo Sample Southwind Racing 16:05:04 L4
3 7 Ada Example Northwind Racing 16:47:33 L17

Infringement Alleged breach of Article B1.2.3 of the Example Regulations.

Decision No further action.

Reasons The Stewards looked at the timing data.
All drivers slowed to let faster cars pass.

Note Competitors are reminded that they can appeal.
Decisions of the Stewards are taken on the evidence.
"""


def test_car_table_layout_reads_the_fields_and_the_cars():
    parsed = decisions.parse(CAR_TABLE)

    assert parsed.layout == "car_table"
    assert parsed.document == 30
    assert parsed.cars == [7, 21, 7]
    assert parsed.driver is None
    assert parsed.time is None  # the only Time lines are the header's
    assert parsed.session == "Qualifying"
    assert parsed.fact == "The cars below were slower than the time limit on their out lap."
    assert parsed.decision == "No further action."
    assert parsed.reason == "The Stewards looked at the timing data. All drivers slowed to let faster cars pass."
    assert parsed.missing == []


def test_a_list_of_deleted_lap_times_is_named_and_left_out():
    text = CAR_TABLE.replace("Decision No further action.", "Decision Deletion of the lap times shown.")
    parsed = decisions.parse(text)

    assert parsed.layout == "car_table"
    assert parsed.other_document == "lap_deletion_list"
    assert parsed.missing == []


def test_documents_without_fields_are_named_not_failed():
    permission = "2031 EXAMPLE GRAND PRIX\nThe Stewards have received a request from Northwind Racing to let car 7 start.\nDocument 39\n"
    report = "2031 EXAMPLE GRAND PRIX\nTechnical Delegate’s Report\nThe floor of car 7 was checked.\nDocument 51\n"
    ruling = "2031 EXAMPLE GRAND PRIX\nThe Stewards, exercising their authority, stopped the session.\nDocument 31\n"
    something_else = "2031 EXAMPLE GRAND PRIX\nA notice about the paddock opening hours.\nDocument 3\n"

    assert decisions.parse(permission).other_document == "permission"
    assert decisions.parse(report).other_document == "technical_report"
    assert decisions.parse(ruling).other_document == "event_ruling"
    assert decisions.parse(something_else).other_document == "unknown"
    assert decisions.parse(permission).layout == "no_fields"
    assert decisions.parse(permission).missing == []
    assert decisions.parse(permission).document == 39
