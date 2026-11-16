"""Calibrate load factors against metered data, and evaluate honestly on held-out time.

Weekly demand is LINEAR in the load factors: kW(w) = base + sum over categories c of s_c * A[w, c],
where A[w, c] is that category's diversity-weighted demand at the modal load factors.

Two modes:
  "global" (default)  ONE scale applied to every category. A single parameter that is always
                      identifiable; it corrects a systematic over- or under-estimate.
  "category"          one scale per category, by ridge least squares (shrunk toward 1.0). It needs far
                      more weeks than categories, because categories that switch on and off together
                      cannot be told apart. Treat its individual scales with caution.
Both clip the result to bounds.

What is compared: the model's weekly kW against the weekly MAXIMUM of the metered kW.

Evaluation: the weeks that have data are split in time order, the first `train_fraction` for fitting and
the rest held out. Every reported metric uses the held-out weeks only. The proposed scales are the ones
fitted on the training weeks, exactly the model that was evaluated.

A proposal is only a proposal: nothing here changes the user's library. Metrics on synthetic data
demonstrate the mechanics, not real-world accuracy.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

import numpy as np

from sitepower.estimate import estimate
from sitepower.models import Equipment, FloatArray, Project, RowError
from sitepower.montecarlo import simulate

Mode = Literal["global", "category"]
DEFAULT_RIDGE: dict[str, float] = {"global": 0.0, "category": 0.01}


class CalibrationError(ValueError):
    """Calibration cannot be done, with a plain-English reason."""


# ------------------------------------------------------------------ metered data in
@dataclass(frozen=True)
class MeteredParse:
    samples: list[tuple[datetime, float]]
    errors: list[RowError]


def parse_metered_csv(text: str) -> MeteredParse:
    """Half-hourly (or any interval) readings: columns `timestamp` and `kw`. Lines starting `#` are comments."""
    samples: list[tuple[datetime, float]] = []
    errors: list[RowError] = []
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header: list[str] | None = None
    for row in reader:
        line = reader.line_num
        if not row or all(not c.strip() for c in row) or row[0].strip().startswith("#"):
            continue
        if header is None:
            header = [c.strip().lower() for c in row]
            missing = [c for c in ("timestamp", "kw") if c not in header]
            if missing:
                return MeteredParse(
                    [], [RowError(line, f"Missing column(s): {', '.join(missing)}.")]
                )
            continue
        cells = dict(zip(header, (c.strip() for c in row), strict=False))
        raw_t = cells.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(raw_t.rstrip("Zz")).replace(tzinfo=None)
        except ValueError:
            errors.append(
                RowError(line, f"timestamp must look like 2025-01-06 08:30 (got '{raw_t}')")
            )
            continue
        try:
            kw = float(cells.get("kw", ""))
        except ValueError:
            errors.append(RowError(line, f"kw must be a number (got '{cells.get('kw', '')}')"))
            continue
        if not math.isfinite(kw):
            errors.append(RowError(line, "kw must be a finite number"))
        elif kw < 0:
            errors.append(RowError(line, "kw must not be negative"))
        else:
            samples.append((ts, kw))
    if header is None:
        errors.append(RowError(1, "File is empty."))
    return MeteredParse(samples, errors)


def weekly_peaks(samples: Sequence[tuple[datetime, float]], start: date, weeks: int) -> FloatArray:
    """Maximum reading in each project week (week 1 starts on `start`). NaN where a week has no data."""
    peaks = np.full(weeks, np.nan, dtype=np.float64)
    for ts, kw in samples:
        days = (ts.date() - start).days
        if days < 0 or days // 7 >= weeks:
            continue
        w = days // 7
        peaks[w] = kw if np.isnan(peaks[w]) else max(peaks[w], kw)
    return peaks


# ------------------------------------------------------------------ the linear model
def category_matrix(
    project: Project, library: Mapping[str, Equipment]
) -> tuple[list[str], FloatArray]:
    """(categories, A) with A[w, c] = diversity-weighted demand of category c in week w at modal load factors."""
    cats = sorted({library[b.equipment_id].category for b in project.bookings})
    index = {c: i for i, c in enumerate(cats)}
    a = np.zeros((project.weeks, len(cats)), dtype=np.float64)
    for b in project.bookings:
        e = library[b.equipment_id]
        div = (
            1.0
            if e.diversity_group is None
            else project.group_diversity.get(e.diversity_group, 1.0)
        )
        a[b.start_week : b.end_week + 1, index[e.category]] += (
            div * b.qty * e.rated_kw * e.load_factor_mode
        )
    return cats, a


def apply_scales(
    library: Mapping[str, Equipment], scales: Mapping[str, float]
) -> dict[str, Equipment]:
    """A new library with each category's load factors multiplied by its scale (capped at 1.0)."""
    out: dict[str, Equipment] = {}
    for eid, e in library.items():
        s = scales.get(e.category, 1.0)
        if not math.isfinite(s) or s <= 0:
            raise ValueError(f"scale for '{e.category}' must be a positive number")
        if s == 1.0:
            out[eid] = e
            continue
        out[eid] = dataclasses.replace(
            e,
            load_factor_min=min(1.0, e.load_factor_min * s),
            load_factor_mode=min(1.0, e.load_factor_mode * s),
            load_factor_max=min(1.0, e.load_factor_max * s),
        )
    return out


# ------------------------------------------------------------------ metrics and result
@dataclass(frozen=True)
class Metrics:
    mae: float  # mean absolute error, kW
    mape: float  # mean absolute percentage error, fraction (NaN if every metered value is zero)
    bias: float  # mean (model - metered), kW; positive = model over-predicts
    coverage: float  # share of weeks whose metered peak falls inside the model's P10 to P90 band
    n: int  # held-out weeks


@dataclass(frozen=True)
class CalibrationResult:
    mode: Mode
    scales: dict[str, float]
    not_identifiable: list[str]
    at_bound: list[str]
    train_weeks: list[int]  # 0-based
    test_weeks: list[int]  # 0-based
    before: Metrics
    after: Metrics
    improved: bool
    warnings: list[str]
    library: dict[str, Equipment]


def _metrics(
    pred: FloatArray, y: FloatArray, p10: FloatArray, p90: FloatArray, weeks: list[int]
) -> Metrics:
    idx = np.array(weeks)
    err = pred[idx] - y[idx]
    pos = y[idx] > 0
    mape = float(np.mean(np.abs(err[pos]) / y[idx][pos])) if pos.any() else float("nan")
    inside = (y[idx] >= p10[idx]) & (y[idx] <= p90[idx])
    return Metrics(
        mae=float(np.mean(np.abs(err))),
        mape=mape,
        bias=float(np.mean(err)),
        coverage=float(np.mean(inside)),
        n=len(weeks),
    )


def _ridge_fit(a: FloatArray, r: FloatArray, ridge: float) -> FloatArray:
    """Least squares for r ~ a @ s, with a penalty pulling s toward 1.0 (scaled by the column energy)."""
    k = a.shape[1]
    lam = ridge * float(np.trace(a.T @ a)) / k if ridge > 0 else 0.0
    m = np.vstack([a, math.sqrt(lam) * np.eye(k)])
    t = np.concatenate([r, math.sqrt(lam) * np.ones(k)])
    return np.asarray(np.linalg.lstsq(m, t, rcond=None)[0], dtype=np.float64)


def calibrate(
    project: Project,
    library: Mapping[str, Equipment],
    metered: FloatArray,
    *,
    mode: Mode = "global",
    ridge: float | None = None,
    bounds: tuple[float, float] = (0.5, 1.5),
    train_fraction: float = 0.7,
    min_weeks: int = 6,
    trials: int = 1000,
    seed: int = 0,
) -> CalibrationResult:
    """Fit scales on the first part of the data; judge them on the rest."""
    if mode not in ("global", "category"):
        raise CalibrationError("mode must be 'global' or 'category'")
    if len(metered) != project.weeks:
        raise CalibrationError(
            f"metered data length ({len(metered)}) must equal the project's weeks ({project.weeks})"
        )
    if not 0 < bounds[0] <= 1 <= bounds[1]:
        raise CalibrationError("bounds must satisfy 0 < low <= 1 <= high")
    have = [w for w in range(project.weeks) if np.isfinite(metered[w])]
    if len(have) < min_weeks:
        raise CalibrationError(
            f"Need at least {min_weeks} weeks of metered data to calibrate and check; found {len(have)}."
        )
    n_train = math.floor(train_fraction * len(have))
    train, test = have[:n_train], have[n_train:]
    if n_train < 2 or not test:
        raise CalibrationError("Not enough weeks to split into a fitting part and a held-out part.")

    cats, a = category_matrix(project, library)
    y = np.asarray(metered, dtype=np.float64)
    base = project.base_load_kw
    lam = DEFAULT_RIDGE[mode] if ridge is None else ridge
    resid = y[train] - base
    warnings: list[str] = []
    at_bound: list[str] = []
    not_identifiable: list[str] = []

    if mode == "global":
        total = a[train].sum(axis=1, keepdims=True)
        if not np.any(total > 0):
            raise CalibrationError(
                "There is no equipment load in the fitting weeks (only base load), so there is nothing to calibrate against."
            )
        fit = float(_ridge_fit(total, resid, lam)[0])
        s = float(np.clip(fit, bounds[0], bounds[1]))
        scales = dict.fromkeys(cats, s)
        if s != fit:
            at_bound = list(cats)
            warnings.append(
                f"The fitted scale ({fit:.2f}) hit the bound ({s:.2f}); the data may not match this model."
            )
    else:
        active = [i for i in range(len(cats)) if np.any(a[train, i] > 0)]
        not_identifiable = [c for i, c in enumerate(cats) if i not in active]
        scales = dict.fromkeys(cats, 1.0)
        if active:
            fit_vec = _ridge_fit(a[np.ix_(train, active)], resid, lam)
            for k, i in enumerate(active):
                clipped = float(np.clip(fit_vec[k], bounds[0], bounds[1]))
                scales[cats[i]] = clipped
                if clipped != fit_vec[k]:
                    at_bound.append(cats[i])
            if n_train < 5 * len(active):
                warnings.append(
                    f"Fitting {len(active)} separate scales from {n_train} weeks is too few: categories that run at "
                    "the same time cannot be told apart, so treat the individual scales as unreliable."
                )
        for c in at_bound:
            warnings.append(
                f"The scale for '{c}' hit the bound; the data may not match this model."
            )

    calibrated = apply_scales(library, scales)
    before_mc = simulate(project, library, trials, seed)
    after_mc = simulate(project, calibrated, trials, seed)
    before = _metrics(estimate(project, library).kw, y, before_mc.p10_kw, before_mc.p90_kw, test)
    after = _metrics(estimate(project, calibrated).kw, y, after_mc.p10_kw, after_mc.p90_kw, test)
    improved = after.mae < before.mae
    if not improved:
        warnings.insert(
            0, "Calibration did not reduce the error on the held-out weeks. Do not apply it."
        )
    if len(test) < 3:
        warnings.append(f"Only {len(test)} held-out weeks: the metrics are indicative at best.")
    return CalibrationResult(
        mode=mode,
        scales=scales,
        not_identifiable=not_identifiable,
        at_bound=at_bound,
        train_weeks=train,
        test_weeks=test,
        before=before,
        after=after,
        improved=improved,
        warnings=warnings,
        library=calibrated,
    )
