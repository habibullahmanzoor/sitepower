"""Extra analyses on top of an estimate: what drives the peak, phases, scenario deltas and a cost comparison.

All pure functions on library types. Money figures are whatever the user enters; nothing here knows a real price.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from sitepower.models import Equipment, Estimate, FloatArray


@dataclass(frozen=True)
class Driver:
    equipment_id: str
    name: str
    kw: float  # after group diversity, in the chosen week
    share: float  # fraction of the equipment total (excludes base load), 0..1
    cumulative: float


def peak_drivers(
    det: Estimate, week: int, library: Mapping[str, Equipment], group_diversity: Mapping[str, float]
) -> list[Driver]:
    """Equipment contributions to one week (1-based), largest first, with cumulative share."""
    if not 1 <= week <= len(det.lines):
        raise ValueError(f"week must be between 1 and {len(det.lines)}")
    totals: dict[str, float] = {}
    for line in det.lines[week - 1]:
        totals[line.equipment_id] = totals.get(line.equipment_id, 0.0) + line.kw * line.diversity
    grand = sum(totals.values())
    out: list[Driver] = []
    running = 0.0
    for eid, kw in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])):
        share = kw / grand if grand > 0 else 0.0
        running += share
        out.append(Driver(eid, library[eid].name, kw, share, running))
    return out


@dataclass(frozen=True)
class PhaseResult:
    name: str
    start_week: int  # 1-based, inclusive
    end_week: int
    peak_kw: float
    peak_week: int
    p90_peak_kva: float


def phase_summary(
    phases: Sequence[tuple[str, int, int]], det: Estimate, p90_kva: FloatArray
) -> tuple[list[PhaseResult], list[str]]:
    """Peak of the central estimate and of the weekly P90 kVA inside each (name, from, to) phase (1-based).

    Bad phases are skipped and reported, the rest kept.
    """
    weeks = len(det.kw)
    out: list[PhaseResult] = []
    problems: list[str] = []
    for i, (name, a, b) in enumerate(phases, start=1):
        label = name.strip() or f"phase {i}"
        if not (1 <= a <= b <= weeks):
            problems.append(f"{label}: weeks must satisfy 1 <= from <= to <= {weeks}")
            continue
        seg = det.kw[a - 1 : b]
        out.append(
            PhaseResult(
                label,
                a,
                b,
                float(seg.max()),
                a + int(seg.argmax()),
                float(p90_kva[a - 1 : b].max()),
            )
        )
    return out, problems


def energy_kwh(kw_by_week: FloatArray, hours_per_week: float) -> float:
    """Central-estimate energy: sum of weekly kW x working hours per week."""
    if not math.isfinite(hours_per_week) or not 0 <= hours_per_week <= 168:
        raise ValueError("hours per week must be between 0 and 168")
    return float(np.sum(kw_by_week) * hours_per_week)


@dataclass(frozen=True)
class CostComparison:
    grid_total: float
    generator_total: float
    cheaper: str  # "grid", "generator" or "equal"
    saving: float
    breakeven_week: (
        int | None
    )  # first week (1-based) the cumulative generator cost passes grid, else None
    grid_cumulative: FloatArray
    generator_cumulative: FloatArray


def compare_costs(
    kw_by_week: FloatArray,
    hours_per_week: float,
    grid_connection: float,
    grid_rate_per_kwh: float,
    generator_hire_per_week: float,
    generator_rate_per_kwh: float,
) -> CostComparison:
    """Grid = one-off connection + energy at the grid rate. Generator = weekly hire + energy at fuel rate.

    All prices are user inputs in one currency; the model is deliberately simple (no standing charges,
    taxes, fuel delivery or maintenance).
    """
    for name, v in (
        ("grid connection", grid_connection),
        ("grid rate", grid_rate_per_kwh),
        ("generator hire", generator_hire_per_week),
        ("generator rate", generator_rate_per_kwh),
    ):
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"{name} must be a finite number, zero or more")
    weekly_kwh = np.asarray(kw_by_week, dtype=np.float64) * _hours(hours_per_week)
    grid = grid_connection + np.cumsum(weekly_kwh * grid_rate_per_kwh)
    gen = np.cumsum(generator_hire_per_week + weekly_kwh * generator_rate_per_kwh)
    g_total, n_total = float(grid[-1]), float(gen[-1])
    over = np.nonzero(gen > grid)[0]
    if math.isclose(g_total, n_total, rel_tol=1e-9, abs_tol=1e-9):
        cheaper = "equal"
    else:
        cheaper = "grid" if g_total < n_total else "generator"
    return CostComparison(
        g_total, n_total, cheaper, abs(g_total - n_total),
        int(over[0]) + 1 if over.size else None, grid, gen,
    )  # fmt: skip


def _hours(h: float) -> float:
    if not math.isfinite(h) or not 0 <= h <= 168:
        raise ValueError("hours per week must be between 0 and 168")
    return float(h)
