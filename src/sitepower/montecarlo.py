"""Seeded uncertainty: how much could the demand vary if the load factors are not exactly the modal values?

Each equipment *type* used in the project gets one load factor per trial, drawn from a triangular
distribution (min, mode, max). Every booking of that type shares the draw, so five hoists all run
"hot" or all run "cool" in a given trial. That perfect correlation is deliberately conservative for the
peak. By default the band reflects load-factor uncertainty ONLY; schedule slips are covered only when
`slip_weeks` is set. It never covers missing equipment, wrong diversity factors, or wrong rated powers.

Reproducibility: draws use numpy's PCG64 generator seeded explicitly, in sorted equipment-id order, so the
same project, library and seed always give identical arrays, and unused library items never change them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from sitepower.estimate import check_bookings, demand
from sitepower.models import Equipment, FloatArray, Project

IntArray = NDArray[np.int64]


@dataclass(frozen=True, eq=False)
class MonteCarloResult:
    p10_kw: FloatArray
    p50_kw: FloatArray
    p90_kw: FloatArray
    p10_kva: FloatArray
    p50_kva: FloatArray
    p90_kva: FloatArray
    peak_kw: FloatArray  # one value per trial: the maximum over weeks
    peak_kva: FloatArray
    peak_week_counts: IntArray  # how many trials had their peak in each week
    trials: int
    seed: int


def draw_load_factors(
    project: Project, library: Mapping[str, Equipment], trials: int, seed: int
) -> dict[str, FloatArray]:
    rng = np.random.Generator(np.random.PCG64(seed))
    used = sorted({b.equipment_id for b in project.bookings})
    out: dict[str, FloatArray] = {}
    for eid in used:
        e = library[eid]
        lo, mode, hi = e.load_factor_min, e.load_factor_mode, e.load_factor_max
        if lo == hi:
            out[eid] = np.full(trials, lo, dtype=np.float64)
        else:
            out[eid] = rng.triangular(lo, mode, hi, size=trials).astype(np.float64)
    return out


def draw_delays(project: Project, trials: int, seed: int, slip_weeks: int) -> list[IntArray]:
    """One whole-week delay per booking per trial, uniform on 0..slip_weeks, from a stream separate from the
    load factors (so turning slip on never changes the load-factor draws)."""
    rng = np.random.Generator(np.random.PCG64([seed, 1]))
    return [rng.integers(0, slip_weeks + 1, size=trials).astype(np.int64) for _ in project.bookings]


def demand_with_delays(
    project: Project,
    library: Mapping[str, Equipment],
    load_factors: Mapping[str, FloatArray],
    delays: Sequence[IntArray],
    trials: int,
) -> tuple[FloatArray, FloatArray]:
    """Like `estimate.demand`, but booking i starts and ends `delays[i][trial]` weeks late.

    A delay moves the whole booking later; the part pushed past the last week is dropped (the equipment is
    still on site when the window ends). Zero delays reproduce `demand` exactly.
    """
    shape = (project.weeks, trials)
    kw_g: dict[str | None, FloatArray] = {}
    kva_g: dict[str | None, FloatArray] = {}
    for b, d in zip(project.bookings, delays, strict=True):
        e = library[b.equipment_id]
        p = b.qty * e.rated_kw * load_factors[e.id]
        key = e.diversity_group
        if key not in kw_g:
            kw_g[key] = np.zeros(shape)
            kva_g[key] = np.zeros(shape)
        for s in np.unique(d):
            cols = np.nonzero(d == s)[0]
            start, end = b.start_week + int(s), min(b.end_week + int(s), project.weeks - 1)
            if start > end:
                continue
            w = slice(start, end + 1)
            kw_g[key][w, cols] += p[cols]
            kva_g[key][w, cols] += p[cols] / e.power_factor
    kw = np.full(shape, project.base_load_kw, dtype=np.float64)
    kva = np.full(shape, project.base_load_kw / project.base_power_factor, dtype=np.float64)
    for key, arr in kw_g.items():
        factor = 1.0 if key is None else project.group_diversity.get(key, 1.0)
        kw += arr * factor
        kva += kva_g[key] * factor
    return kw, kva


def simulate(
    project: Project,
    library: Mapping[str, Equipment],
    trials: int = 2000,
    seed: int = 0,
    slip_weeks: int = 0,
) -> MonteCarloResult:
    """Seeded Monte Carlo. `slip_weeks` > 0 also lets every booking start up to that many whole weeks late."""
    if isinstance(trials, bool) or not isinstance(trials, int) or trials < 1:
        raise ValueError("trials must be a whole number of at least 1")
    if isinstance(slip_weeks, bool) or not isinstance(slip_weeks, int) or slip_weeks < 0:
        raise ValueError("slip_weeks must be a whole number, zero or more")
    check_bookings(project, library)
    lf = draw_load_factors(project, library, trials, seed)
    if slip_weeks == 0:
        kw, kva = demand(project, library, lf, trials)
    else:
        delays = draw_delays(project, trials, seed, slip_weeks)
        kw, kva = demand_with_delays(project, library, lf, delays, trials)

    def pct(a: FloatArray, q: float) -> FloatArray:
        return np.asarray(np.percentile(a, q, axis=1), dtype=np.float64)

    return MonteCarloResult(
        p10_kw=pct(kw, 10),
        p50_kw=pct(kw, 50),
        p90_kw=pct(kw, 90),
        p10_kva=pct(kva, 10),
        p50_kva=pct(kva, 50),
        p90_kva=pct(kva, 90),
        peak_kw=kw.max(axis=0),
        peak_kva=kva.max(axis=0),
        peak_week_counts=np.bincount(kw.argmax(axis=0), minlength=project.weeks).astype(np.int64),
        trials=trials,
        seed=seed,
    )


def peak_percentile(peaks: FloatArray, q: float) -> float:
    """The q-th percentile (0 to 100) of the per-trial peak values."""
    if not 0 <= q <= 100:
        raise ValueError("percentile must be between 0 and 100")
    return float(np.percentile(peaks, q))
