import math

import pytest

from sitepower.estimate import estimate
from sitepower.models import Booking, Equipment, Project
from sitepower.montecarlo import simulate
from sitepower.uimodel import bookings_to_rows, headline, rows_to_bookings, week_breakdown

LIB = {
    "a": Equipment("a", "Alpha", "c", 10, 0.8, 0.4, 0.6, 0.9, "g"),
    "b": Equipment("b", "Beta", "c", 4, 0.9, 0.5, 0.5, 0.5),
}


def test_rows_become_bookings_with_one_based_weeks_converted() -> None:
    rows = [{"equipment_id": "a", "qty": 2, "start_week": 1, "end_week": 3}]
    bookings, errors = rows_to_bookings(rows, LIB, weeks=10)
    assert errors == []
    assert bookings == [Booking("a", 2, 0, 2)]  # UI weeks are 1-based, the engine is 0-based


def test_blank_rows_are_ignored_and_floats_that_are_whole_numbers_are_accepted() -> None:
    rows = [
        {"equipment_id": None, "qty": None, "start_week": None, "end_week": None},
        {"equipment_id": "b", "qty": 3.0, "start_week": 2.0, "end_week": 2.0},
        {"equipment_id": float("nan"), "qty": float("nan"), "start_week": float("nan"), "end_week": float("nan")},
    ]  # fmt: skip
    bookings, errors = rows_to_bookings(rows, LIB, weeks=5)
    assert errors == [] and bookings == [Booking("b", 3, 1, 1)]


def test_bad_rows_give_row_numbered_messages_and_good_rows_still_load() -> None:
    rows = [
        {"equipment_id": "a", "qty": 1, "start_week": 1, "end_week": 2},
        {"equipment_id": "zzz", "qty": 1, "start_week": 1, "end_week": 2},
        {"equipment_id": "a", "qty": 0, "start_week": 1, "end_week": 2},
        {"equipment_id": "a", "qty": 1, "start_week": 4, "end_week": 2},
        {"equipment_id": "a", "qty": 1, "start_week": 1, "end_week": 99},
        {"equipment_id": "a", "qty": 1.5, "start_week": 1, "end_week": 2},
        {"equipment_id": "a", "qty": 1, "start_week": None, "end_week": 2},
    ]
    bookings, errors = rows_to_bookings(rows, LIB, weeks=10)
    assert len(bookings) == 1
    assert [e.row for e in errors] == [2, 3, 4, 5, 6, 7]
    assert "unknown equipment" in errors[0].message
    assert "qty" in errors[1].message
    assert "week" in errors[2].message
    assert "10" in errors[3].message
    assert "whole" in errors[4].message
    assert "start_week" in errors[5].message


def test_rows_round_trip_through_a_project() -> None:
    p = Project("p", 6, (Booking("a", 2, 0, 3), Booking("b", 1, 2, 5)))
    bookings, errors = rows_to_bookings(bookings_to_rows(p), LIB, weeks=6)
    assert errors == [] and tuple(bookings) == p.bookings


def test_week_breakdown_explains_a_week_and_names_the_equipment() -> None:
    p = Project("p", 4, (Booking("a", 2, 1, 2), Booking("b", 1, 1, 1)), group_diversity={"g": 0.5})
    det = estimate(p, LIB)
    rows = week_breakdown(det, 2, LIB)  # UI week 2 is index 1
    assert [r["Equipment"] for r in rows] == ["Alpha", "Beta"]
    assert rows[0]["Qty"] == 2
    assert rows[0]["kW before diversity"] == pytest.approx(12.0)
    assert rows[0]["Group diversity"] == 0.5
    assert week_breakdown(det, 1, LIB) == []
    with pytest.raises(ValueError):
        week_breakdown(det, 0, LIB)
    with pytest.raises(ValueError):
        week_breakdown(det, 5, LIB)


def test_headline_numbers_are_consistent() -> None:
    p = Project("p", 6, (Booking("a", 2, 1, 4),), base_load_kw=1.0)
    det = estimate(p, LIB)
    mc = simulate(p, LIB, 500, 3)
    h = headline(det, mc, headroom=0.2)
    assert h.deterministic_peak_kw == pytest.approx(float(det.kw.max()))
    assert h.p50_peak_kw <= h.p90_peak_kw
    assert h.p90_peak_kva >= h.p90_peak_kw
    assert 1 <= h.most_likely_peak_week <= 6
    assert h.sizing.required_kva == pytest.approx(h.p90_peak_kva * 1.2)
    assert all(math.isfinite(v) for v in (h.p50_peak_kw, h.p90_peak_kw, h.p90_peak_kva))
