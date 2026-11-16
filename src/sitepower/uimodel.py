"""Non-visual logic behind the web page, kept here so it is typed and tested.

The page shows weeks numbered from 1; the engine counts from 0. Conversion happens only here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sitepower.models import Booking, Equipment, Estimate, Project, RowError
from sitepower.montecarlo import MonteCarloResult, peak_percentile
from sitepower.sizing import SizingResult, recommend_size


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def _whole(v: Any, name: str) -> int:
    if _blank(v):
        raise ValueError(f"{name} is required")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or float(v) != int(v):
        raise ValueError(f"{name} must be a whole number")
    return int(v)


def rows_to_bookings(
    rows: Sequence[Mapping[str, Any]], library: Mapping[str, Equipment], weeks: int
) -> tuple[list[Booking], list[RowError]]:
    """Convert editable table rows (1-based weeks) to engine bookings. Bad rows are reported, others kept."""
    bookings: list[Booking] = []
    errors: list[RowError] = []
    for n, row in enumerate(rows, start=1):
        if all(_blank(row.get(k)) for k in ("equipment_id", "qty", "start_week", "end_week")):
            continue
        try:
            eid = row.get("equipment_id")
            if _blank(eid) or not isinstance(eid, str) or eid not in library:
                raise ValueError(f"unknown equipment '{eid}'")
            qty = _whole(row.get("qty"), "qty")
            start = _whole(row.get("start_week"), "start_week")
            end = _whole(row.get("end_week"), "end_week")
            if start < 1 or end < start:
                raise ValueError("weeks must start at 1 and end_week must not be before start_week")
            if end > weeks:
                raise ValueError(f"end_week {end} is outside the {weeks}-week project")
            bookings.append(Booking(eid, qty, start - 1, end - 1))
        except ValueError as exc:
            errors.append(RowError(n, str(exc)))
    return bookings, errors


def bookings_to_rows(project: Project) -> list[dict[str, Any]]:
    return [
        {
            "equipment_id": b.equipment_id,
            "qty": b.qty,
            "start_week": b.start_week + 1,
            "end_week": b.end_week + 1,
        }
        for b in project.bookings
    ]


def week_breakdown(
    det: Estimate, week: int, library: Mapping[str, Equipment]
) -> list[dict[str, Any]]:
    """Why a given week (1-based) has the demand it has: one row per booking active that week."""
    if not 1 <= week <= len(det.lines):
        raise ValueError(f"week must be between 1 and {len(det.lines)}")
    return [
        {
            "Equipment": library[line.equipment_id].name,
            "Qty": line.qty,
            "kW before diversity": round(line.kw, 3),
            "kVA before diversity": round(line.kva, 3),
            "Group diversity": line.diversity,
        }
        for line in det.lines[week - 1]
    ]


@dataclass(frozen=True)
class Headline:
    deterministic_peak_kw: float
    p50_peak_kw: float
    p90_peak_kw: float
    p90_peak_kva: float
    most_likely_peak_week: int  # 1-based
    sizing: SizingResult


def headline(det: Estimate, mc: MonteCarloResult, headroom: float) -> Headline:
    p90_kva = peak_percentile(mc.peak_kva, 90)
    return Headline(
        deterministic_peak_kw=float(det.kw.max()),
        p50_peak_kw=peak_percentile(mc.peak_kw, 50),
        p90_peak_kw=peak_percentile(mc.peak_kw, 90),
        p90_peak_kva=p90_kva,
        most_likely_peak_week=int(mc.peak_week_counts.argmax()) + 1,
        sizing=recommend_size(p90_kva, headroom),
    )
