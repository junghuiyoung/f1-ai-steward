"""The manifest keeps incident decisions and drops everything else."""

from f1aisteward import manifest


def test_parse_title_keeps_an_incident_decision():
    parsed = manifest.parse_title("Doc 79 - Infringement - Car 16 - Causing a collision")
    assert parsed == {"number": 79, "kind": "Infringement", "subject": "Car 16 - Causing a collision"}


def test_parse_title_keeps_decision_and_offence_kinds():
    assert manifest.parse_title("Doc 65 - Decision - Car 44 - Alleged leaving the track")["kind"] == "Decision"
    assert manifest.parse_title("Doc 12 - Offence - Car 1 - Pit lane speeding")["kind"] == "Offence"


def test_parse_title_tolerates_missing_spaces_around_dashes():
    # A real title from the 2026 Dutch Grand Prix has "Infringement- Car 55".
    parsed = manifest.parse_title("Doc 22 - Infringement- Car 55 - driving unnecessarily slowly")
    assert parsed == {"number": 22, "kind": "Infringement", "subject": "Car 55 - driving unnecessarily slowly"}


def test_parse_title_drops_lap_time_deletion_lists():
    assert manifest.parse_title("Doc 76 - Infringement - Race Deleted Lap Times") is None
    assert manifest.parse_title("Doc 46 - Infringement - Qualifying Deleted Lap Times - Double Yellow") is None


def test_parse_title_drops_documents_that_are_not_decisions():
    assert manifest.parse_title("Doc 81 - Final Race Classification") is None
    assert manifest.parse_title("Doc 2 - Competition Notes - Pirelli Preview") is None


def test_slugify():
    assert manifest.slugify("São Paulo Grand Prix") == "sao-paulo"
    assert manifest.slugify("United States Grand Prix") == "united-states"
    assert manifest.slugify("Barcelona-Catalunya Grand Prix") == "barcelona-catalunya"


def test_build_events_orders_events_by_date_and_numbers_them():
    listing = [
        {
            "name": "Second Grand Prix",
            "docs": [
                {"href": "/b/points.pdf", "title": "Doc 9 - Championship Points", "published": "15.03.26 12:05"},
                {"href": "/b/7.pdf", "title": "Doc 7 - Infringement - Car 4 - Speeding", "published": "14.03.26 10:00"},
                {"href": "/b/3.pdf", "title": "Doc 3 - Decision - Car 1 - Impeding", "published": "13.03.26 09:00"},
            ],
        },
        {
            "name": "First Grand Prix",
            "docs": [
                {"href": "/a/5.pdf", "title": "Doc 5 - Infringement - Race Deleted Lap Times", "published": "08.03.26 09:00"},
                {"href": "/a/2.pdf", "title": "Doc 2 - Offence - Car 2 - Unsafe release", "published": "07.03.26 15:30"},
            ],
        },
    ]
    data = manifest.build_events(listing, season=2026)

    assert [(e["round"], e["slug"], e["date"]) for e in data["events"]] == [
        (1, "first", "2026-03-08"),
        (2, "second", "2026-03-15"),
    ]
    first, second = data["events"]
    assert [d["number"] for d in first["docs"]] == [2]  # the lap-time list is dropped
    assert [d["number"] for d in second["docs"]] == [3, 7]  # sorted by document number
    assert second["docs"][0]["url"] == "https://www.fia.com/b/3.pdf"
    assert second["docs"][0]["published"] == "2026-03-13 09:00"
    assert second["docs"][0]["sha256"] is None


def test_event_date_is_race_day_even_when_a_decision_is_published_later():
    listing = [
        {
            "name": "Late Grand Prix",
            "docs": [
                {"href": "/c/9.pdf", "title": "Doc 9 - Infringement - Car 6 - Weaving", "published": "29.05.26 10:00"},
                {"href": "/c/8.pdf", "title": "Doc 8 - Final Race Classification", "published": "25.05.26 03:10"},
            ],
        }
    ]
    assert manifest.build_events(listing, season=2026)["events"][0]["date"] == "2026-05-25"
