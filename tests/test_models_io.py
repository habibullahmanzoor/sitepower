import json

import pytest

from sitepower.io import ProjectError, project_from_json, project_to_json
from sitepower.library import parse_equipment_csv
from sitepower.models import Booking, Equipment, Project

HEADER = (
    "id,name,category,rated_kw,power_factor,load_factor_min,load_factor_mode,"
    "load_factor_max,diversity_group,source"
)


def test_equipment_validation_rejects_bad_values() -> None:
    base = dict(
        id="a",
        name="a",
        category="c",
        rated_kw=5.0,
        power_factor=0.9,
        load_factor_min=0.3,
        load_factor_mode=0.5,
        load_factor_max=0.8,
    )
    Equipment(**base)  # type: ignore[arg-type]
    for field, bad in [
        ("rated_kw", 0),
        ("rated_kw", -1),
        ("power_factor", 0),
        ("power_factor", 1.1),
        ("load_factor_min", 0),
        ("load_factor_min", 0.6),
        ("load_factor_mode", 0.9),
        ("load_factor_max", 1.2),
        ("load_factor_max", float("nan")),
    ]:
        with pytest.raises(ValueError):
            Equipment(**{**base, field: bad})  # type: ignore[arg-type]


def test_booking_and_project_validation() -> None:
    with pytest.raises(ValueError):
        Booking("a", 0, 0, 1)
    with pytest.raises(ValueError):
        Booking("a", 1, 3, 2)
    with pytest.raises(ValueError):
        Booking("a", 1, -1, 2)
    with pytest.raises(ValueError):
        Project("p", 0, ())
    with pytest.raises(ValueError):
        Project("p", 4, (Booking("a", 1, 0, 4),))  # week 4 is outside a 4-week project
    with pytest.raises(ValueError):
        Project("p", 4, (), group_diversity={"g": 0.0})
    with pytest.raises(ValueError):
        Project("p", 4, (), group_diversity={"g": 1.2})
    with pytest.raises(ValueError):
        Project("p", 4, (), base_load_kw=-1)
    with pytest.raises(ValueError):
        Project("p", 4, (), base_power_factor=0)


def test_equipment_csv_parses_and_reports_row_numbered_errors() -> None:
    text = "\n".join(
        [
            HEADER,
            "crane,Tower crane,lifting,45,0.85,0.2,0.4,0.7,cranes,illustrative",
            "bad,Bad,tools,-3,0.8,0.3,0.5,0.8,,illustrative",
            "drill,Drill,tools,1.1,0.7,0.3,0.5,0.9,,illustrative",
            "x,X,tools,abc,0.8,0.3,0.5,0.8,,illustrative",
        ]
    )
    r = parse_equipment_csv(text)
    assert sorted(r.library) == ["crane", "drill"]
    assert r.library["crane"].diversity_group == "cranes"
    assert r.library["drill"].diversity_group is None
    assert [e.row for e in r.errors] == [3, 5]
    assert "rated_kw" in r.errors[0].message
    assert "rated_kw" in r.errors[1].message


def test_equipment_csv_handles_quotes_bom_missing_columns_and_duplicates() -> None:
    quoted = HEADER + '\na,"Cabin, welfare",welfare,3,0.9,0.4,0.6,0.9,,"hire sheet, 2025"'
    assert parse_equipment_csv("﻿" + quoted).library["a"].name == "Cabin, welfare"
    assert "Missing column" in parse_equipment_csv("id,name\na,b").errors[0].message
    assert "empty" in parse_equipment_csv("").errors[0].message.lower()
    dup = HEADER + "\na,A,c,1,0.9,0.4,0.6,0.9,,x\na,A2,c,1,0.9,0.4,0.6,0.9,,x"
    r = parse_equipment_csv(dup)
    assert len(r.library) == 1 and "duplicate" in r.errors[0].message.lower()


def test_project_json_round_trips() -> None:
    p = Project(
        "Block A",
        10,
        (Booking("crane", 1, 2, 7), Booking("hoist", 2, 3, 9)),
        group_diversity={"cranes": 0.8},
        base_load_kw=12.5,
        base_power_factor=0.92,
    )
    assert project_from_json(project_to_json(p)) == p


def test_project_json_errors_are_clear_not_crashes() -> None:
    good = json.loads(project_to_json(Project("p", 4, (Booking("a", 1, 0, 1),))))
    for mutate, needle in [
        (lambda d: d.pop("weeks"), "weeks"),
        (lambda d: d.__setitem__("weeks", "ten"), "weeks"),
        (lambda d: d.__setitem__("bookings", "x"), "bookings"),
        (lambda d: d["bookings"][0].pop("qty"), "qty"),
        (lambda d: d["bookings"][0].__setitem__("end_week", 99), "week"),
        (lambda d: d.__setitem__("group_diversity", {"g": 5}), "diversity"),
    ]:
        d = json.loads(json.dumps(good))
        mutate(d)
        with pytest.raises(ProjectError, match=needle):
            project_from_json(json.dumps(d))
    with pytest.raises(ProjectError, match="JSON"):
        project_from_json("{not json")
    with pytest.raises(ProjectError):
        project_from_json("[1, 2]")
