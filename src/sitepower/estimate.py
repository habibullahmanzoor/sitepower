"""Deterministic week-by-week demand.

For each booking: P = qty x rated_kw x load_factor, active from start_week to end_week.
Items sharing a diversity group are summed, then multiplied by that group's diversity factor
(default 1.0). Ungrouped items add directly. The project's base load is added every week.
kVA is the arithmetic sum of kW / power_factor per item: a stated, conservative simplification
(it does not combine phasors).

One implementation (`demand`) serves both this module and the Monte Carlo module, so a
zero-width distribution reproduces the deterministic result exactly.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from sitepower.models import Equipment, Estimate, FloatArray, Project, WeekLine


class UnknownEquipmentError(ValueError):
    """A booking refers to equipment that is not in the library."""


def check_bookings(project: Project, library: Mapping[str, Equipment]) -> None:
    for b in project.bookings:
        if b.equipment_id not in library:
            raise UnknownEquipmentError(f"booking refers to unknown equipment '{b.equipment_id}'")


def demand(
    project: Project,
    library: Mapping[str, Equipment],
    load_factors: Mapping[str, FloatArray],
    trials: int,
) -> tuple[FloatArray, FloatArray]:
    """Return (kw, kva), each shaped (weeks, trials). `load_factors[id]` has shape (trials,)."""
    check_bookings(project, library)
    shape = (project.weeks, trials)
    kw_by_group: dict[str | None, FloatArray] = {}
    kva_by_group: dict[str | None, FloatArray] = {}
    for b in project.bookings:
        e = library[b.equipment_id]
        p = b.qty * e.rated_kw * load_factors[e.id]
        key = e.diversity_group
        if key not in kw_by_group:
            kw_by_group[key] = np.zeros(shape)
            kva_by_group[key] = np.zeros(shape)
        weeks = slice(b.start_week, b.end_week + 1)
        kw_by_group[key][weeks, :] += p
        kva_by_group[key][weeks, :] += p / e.power_factor
    kw = np.full(shape, project.base_load_kw, dtype=np.float64)
    kva = np.full(shape, project.base_load_kw / project.base_power_factor, dtype=np.float64)
    for key, arr in kw_by_group.items():
        factor = 1.0 if key is None else project.group_diversity.get(key, 1.0)
        kw += arr * factor
        kva += kva_by_group[key] * factor
    return kw, kva


def mode_load_factors(
    library: Mapping[str, Equipment], override: Mapping[str, float] | None = None
) -> dict[str, FloatArray]:
    out: dict[str, FloatArray] = {}
    for eid, e in library.items():
        v = e.load_factor_mode if override is None or eid not in override else override[eid]
        out[eid] = np.full(1, v, dtype=np.float64)
    return out


def estimate(
    project: Project,
    library: Mapping[str, Equipment],
    load_factors: Mapping[str, float] | None = None,
) -> Estimate:
    """Deterministic estimate at each item's modal load factor (or the given overrides)."""
    kw, kva = demand(project, library, mode_load_factors(library, load_factors), 1)
    lf = {eid: float(a[0]) for eid, a in mode_load_factors(library, load_factors).items()}
    lines: list[tuple[WeekLine, ...]] = []
    for w in range(project.weeks):
        week: list[WeekLine] = []
        for b in project.bookings:
            if b.start_week <= w <= b.end_week:
                e = library[b.equipment_id]
                p = b.qty * e.rated_kw * lf[e.id]
                div = (
                    1.0
                    if e.diversity_group is None
                    else project.group_diversity.get(e.diversity_group, 1.0)
                )
                week.append(WeekLine(e.id, b.qty, p, p / e.power_factor, div))
        lines.append(tuple(week))
    return Estimate(kw=kw[:, 0], kva=kva[:, 0], lines=tuple(lines))
