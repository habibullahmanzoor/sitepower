"""Project JSON in and out. Errors are ProjectError with a message that names the offending field."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from sitepower.models import Booking, Estimate, Project
from sitepower.montecarlo import MonteCarloResult


def profile_to_csv(project: Project, det: Estimate, mc: MonteCarloResult) -> str:
    """Weekly profile for export. Weeks are numbered from 1 for readers; kW to 3 decimal places."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(
        [
            "week", "kw_deterministic", "kva_deterministic",
            "kw_p10", "kw_p50", "kw_p90", "kva_p10", "kva_p50", "kva_p90",
        ]
    )  # fmt: skip
    for i in range(project.weeks):
        vals = (
            det.kw[i], det.kva[i], mc.p10_kw[i], mc.p50_kw[i], mc.p90_kw[i],
            mc.p10_kva[i], mc.p50_kva[i], mc.p90_kva[i],
        )  # fmt: skip
        w.writerow([i + 1, *(f"{float(v):.3f}" for v in vals)])
    return buf.getvalue()


class ProjectError(ValueError):
    """The project file is invalid."""


def project_to_json(p: Project) -> str:
    return json.dumps(
        {
            "name": p.name,
            "weeks": p.weeks,
            "base_load_kw": p.base_load_kw,
            "base_power_factor": p.base_power_factor,
            "group_diversity": dict(p.group_diversity),
            "bookings": [
                {
                    "equipment_id": b.equipment_id,
                    "qty": b.qty,
                    "start_week": b.start_week,
                    "end_week": b.end_week,
                }
                for b in p.bookings
            ],
        },
        indent=2,
    )


def _int(d: dict[str, Any], key: str, where: str) -> int:
    if key not in d:
        raise ProjectError(f"{where}missing field '{key}'")
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ProjectError(f"{where}'{key}' must be a whole number")
    return v


def _num(d: dict[str, Any], key: str, default: float) -> float:
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ProjectError(f"'{key}' must be a number")
    return float(v)


def project_from_json(text: str) -> Project:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectError(f"Not valid JSON: {exc.msg}") from None
    if not isinstance(raw, dict):
        raise ProjectError("A project file must be a JSON object")
    name = raw.get("name", "Untitled")
    if not isinstance(name, str):
        raise ProjectError("'name' must be text")
    weeks = _int(raw, "weeks", "")
    items = raw.get("bookings", [])
    if not isinstance(items, list):
        raise ProjectError("'bookings' must be a list")
    bookings: list[Booking] = []
    for i, item in enumerate(items, start=1):
        where = f"booking {i}: "
        if not isinstance(item, dict):
            raise ProjectError(f"{where}must be an object")
        eid = item.get("equipment_id")
        if not isinstance(eid, str):
            raise ProjectError(f"{where}'equipment_id' must be text")
        try:
            bookings.append(
                Booking(
                    eid,
                    _int(item, "qty", where),
                    _int(item, "start_week", where),
                    _int(item, "end_week", where),
                )
            )
        except ValueError as exc:
            raise ProjectError(f"{where}{exc}") from None
    gd = raw.get("group_diversity", {})
    if not isinstance(gd, dict):
        raise ProjectError("'group_diversity' must be an object")
    try:
        return Project(
            name=name,
            weeks=weeks,
            bookings=tuple(bookings),
            group_diversity={str(k): float(v) for k, v in gd.items()},
            base_load_kw=_num(raw, "base_load_kw", 0.0),
            base_power_factor=_num(raw, "base_power_factor", 0.9),
        )
    except (ValueError, TypeError) as exc:
        raise ProjectError(str(exc)) from None
