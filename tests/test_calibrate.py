"""Tests for metered-data parsing, calibration and the synthetic generator.

Expected values come from building data with KNOWN scales and checking they are recovered, plus
exact arithmetic on small cases. Metrics on synthetic data prove the mechanics only.
"""

from datetime import date, datetime

import numpy as np
import pytest

from sitepower.calibrate import (
    CalibrationError,
    apply_scales,
    calibrate,
    category_matrix,
    parse_metered_csv,
    weekly_peaks,
)
from sitepower.estimate import estimate
from sitepower.models import Booking, Equipment, Project
from sitepower.synth import generate_metered, metered_to_csv

START = date(2025, 1, 6)


def eq(
    id_: str, cat: str, kw: float, mode: float = 0.5, lo: float = 0.3, hi: float = 0.9
) -> Equipment:
    return Equipment(id_, id_, cat, kw, 0.9, lo, mode, hi, None)


LIB = {
    "crane": eq("crane", "lifting", 40),
    "tools": eq("tools", "tools", 10),
    "heat": eq("heat", "drying", 30, mode=0.6, hi=1.0),
}


def project(weeks: int = 20) -> Project:
    half, third = (
        weeks // 2,
        weeks // 3,
    )  # for 20 weeks: tools change at week 10, heat on weeks 6 to 13
    return Project(
        "p", weeks,
        (
            Booking("crane", 1, 0, weeks - 1),
            Booking("tools", 2, 0, half - 1),
            Booking("tools", 4, half, weeks - 1),
            Booking("heat", 1, third, 2 * third),
        ),
        base_load_kw=2.0,
    )  # fmt: skip


def truth_peaks(p: Project, lib: dict[str, Equipment], scales: dict[str, float]) -> np.ndarray:
    scaled = apply_scales(lib, scales)
    return estimate(p, scaled).kw.copy()


# ---------------------------------------------------------------- category matrix identity
def test_category_matrix_plus_base_equals_the_deterministic_estimate() -> None:
    p = project()
    cats, a = category_matrix(p, LIB)
    assert cats == ["drying", "lifting", "tools"]
    assert (p.base_load_kw + a.sum(axis=1)) == pytest.approx(estimate(p, LIB).kw)


# ---------------------------------------------------------------- scaling the library
def test_apply_scales_keeps_load_factor_ordering_and_never_exceeds_one() -> None:
    out = apply_scales(LIB, {"lifting": 1.5, "drying": 1.5})
    for e in out.values():
        assert 0 < e.load_factor_min <= e.load_factor_mode <= e.load_factor_max <= 1
    assert out["heat"].load_factor_max == 1.0  # 1.0 x 1.5 clipped
    assert out["crane"].load_factor_mode == pytest.approx(0.75)
    assert LIB["crane"].load_factor_mode == 0.5  # the original library is never mutated


def test_apply_scales_leaves_unlisted_categories_alone() -> None:
    assert apply_scales(LIB, {"lifting": 0.8})["tools"] == LIB["tools"]


# ---------------------------------------------------------------- parsing metered data
def test_metered_csv_parses_comments_bom_and_row_errors() -> None:
    text = "\n".join([
        "# SYNTHETIC example",
        "timestamp,kw",
        "2025-01-06 08:00,12.5",
        "2025-01-06T08:30:00,14.0",
        "not a time,10",
        "2025-01-06 09:00,-3",
        "2025-01-06 09:30,abc",
        "2025-01-06 10:00Z,9",
    ])  # fmt: skip
    r = parse_metered_csv("﻿" + text)
    assert [s[1] for s in r.samples] == [12.5, 14.0, 9.0]
    assert [e.row for e in r.errors] == [5, 6, 7]
    assert "timestamp" in r.errors[0].message
    assert "negative" in r.errors[1].message
    assert "kw" in r.errors[2].message


def test_metered_csv_rejects_empty_and_missing_columns() -> None:
    assert "empty" in parse_metered_csv("").errors[0].message.lower()
    assert "Missing column" in parse_metered_csv("a,b\n1,2").errors[0].message


def test_weekly_peaks_take_the_maximum_per_week_and_mark_gaps() -> None:
    s = [
        (datetime(2025, 1, 6, 8), 10.0), (datetime(2025, 1, 8, 8), 25.0),   # week 1
        (datetime(2025, 1, 20, 8), 7.0),                                    # week 3 (week 2 has none)
        (datetime(2025, 1, 5, 23), 99.0),                                   # before the start: ignored
        (datetime(2025, 3, 3, 8), 99.0),                                    # after the last week: ignored
    ]  # fmt: skip
    peaks = weekly_peaks(s, START, weeks=4)
    assert peaks[0] == 25.0 and peaks[2] == 7.0
    assert np.isnan(peaks[1]) and np.isnan(peaks[3])


# ---------------------------------------------------------------- calibration
def test_known_scales_are_recovered_from_noise_free_data() -> None:
    true = {"lifting": 0.8, "tools": 1.3, "drying": 0.9}
    p = project()
    y = truth_peaks(p, LIB, true)
    r = calibrate(p, LIB, y, mode="category", ridge=0.0, trials=200, seed=1)
    for cat, want in true.items():
        assert r.scales[cat] == pytest.approx(want, rel=0.01)
    assert r.after.mae < 1e-6 < r.before.mae


def test_the_split_is_in_time_order_and_metrics_use_held_out_weeks_only() -> None:
    p = project()
    y = truth_peaks(p, LIB, {"tools": 1.3})
    r = calibrate(p, LIB, y, mode="category", ridge=0.0, trials=100, seed=1)
    assert r.train_weeks == list(range(14))  # floor(0.7 x 20) = 14 training weeks
    assert r.test_weeks == list(range(14, 20))
    assert not set(r.train_weeks) & set(r.test_weeks)
    # the "before" error is exactly the mean absolute error of the original model on the last six weeks
    original = estimate(p, LIB).kw
    assert r.before.mae == pytest.approx(float(np.mean(np.abs(original[14:] - y[14:]))))
    assert r.before.n == r.after.n == 6


def test_weeks_without_data_are_skipped_before_splitting() -> None:
    p = project()
    y = truth_peaks(p, LIB, {"tools": 1.2})
    y[[3, 4, 12]] = np.nan
    r = calibrate(p, LIB, y, mode="category", ridge=0.0, trials=100, seed=1)
    have = [w for w in range(20) if not np.isnan(y[w])]
    assert r.train_weeks + r.test_weeks == have
    assert r.test_weeks == have[len(r.train_weeks) :]


def test_too_little_data_is_refused_with_a_clear_reason() -> None:
    p = project()
    y = np.full(20, np.nan)
    y[:5] = 50.0
    with pytest.raises(CalibrationError, match="at least 6"):
        calibrate(p, LIB, y)
    with pytest.raises(CalibrationError, match="length"):
        calibrate(p, LIB, np.zeros(7))


def test_a_category_not_booked_in_the_training_weeks_is_flagged_and_left_at_one() -> None:
    p = Project("p", 20, (Booking("crane", 1, 0, 19), Booking("heat", 1, 16, 19)), base_load_kw=1.0)
    y = truth_peaks(p, LIB, {"lifting": 0.9})
    r = calibrate(p, LIB, y, mode="category", ridge=0.0, trials=100, seed=1)
    assert "drying" in r.not_identifiable and r.scales["drying"] == 1.0
    assert "lifting" not in r.not_identifiable


def test_scales_are_clipped_to_the_bounds_and_flagged() -> None:
    p = project()
    y = (
        truth_peaks(p, LIB, {"tools": 1.0}) + 3 * category_matrix(p, LIB)[1][:, 2]
    )  # tools drawing ~4x
    r = calibrate(p, LIB, y, mode="category", ridge=0.0, bounds=(0.5, 1.5), trials=100, seed=1)
    assert r.scales["tools"] == 1.5 and "tools" in r.at_bound


def test_calibration_improves_held_out_error_and_the_band_coverage_is_reported() -> None:
    p = project()
    y = truth_peaks(p, LIB, {"lifting": 0.8, "tools": 1.3, "drying": 0.9})
    r = calibrate(p, LIB, y, mode="category", ridge=0.0, trials=400, seed=2)
    assert r.improved and r.after.mae < r.before.mae
    assert 0.0 <= r.before.coverage <= 1.0 and 0.0 <= r.after.coverage <= 1.0
    assert r.library["tools"].load_factor_mode == pytest.approx(0.5 * r.scales["tools"])


def test_calibration_is_reproducible() -> None:
    p = project()
    y = truth_peaks(p, LIB, {"tools": 1.25})
    a, b = calibrate(p, LIB, y, trials=200, seed=5), calibrate(p, LIB, y, trials=200, seed=5)
    assert a.scales == b.scales and a.after == b.after


# ---------------------------------------------------------------- synthetic generator
def test_synthetic_data_is_deterministic_labelled_and_round_trips() -> None:
    p = project(10)
    a = generate_metered(p, LIB, {"tools": 1.3}, START, seed=4, metered_weeks=8)
    b = generate_metered(p, LIB, {"tools": 1.3}, START, seed=4, metered_weeks=8)
    c = generate_metered(p, LIB, {"tools": 1.3}, START, seed=5, metered_weeks=8)
    assert a == b and a != c
    assert len(a) == 8 * 7 * 48
    text = metered_to_csv(a)
    assert text.startswith("# SYNTHETIC")
    parsed = parse_metered_csv(text)
    assert parsed.errors == [] and len(parsed.samples) == len(a)
    assert parsed.samples[0][0] == datetime(2025, 1, 6, 0, 0)


def test_synthetic_weekly_peaks_track_the_true_demand_closely() -> None:
    p = project(10)
    true = {"tools": 1.3, "lifting": 0.8}
    samples = generate_metered(p, LIB, true, START, seed=1, metered_weeks=10, noise=0.03)
    peaks = weekly_peaks(samples, START, 10)
    want = truth_peaks(p, LIB, true)
    assert np.isfinite(peaks).all()
    assert np.max(np.abs(peaks - want) / want) < 0.12


def test_synthetic_generator_validates_its_inputs() -> None:
    p = project(6)
    with pytest.raises(ValueError, match="metered_weeks"):
        generate_metered(p, LIB, {}, START, seed=1, metered_weeks=9)
    with pytest.raises(ValueError, match="noise"):
        generate_metered(p, LIB, {}, START, seed=1, metered_weeks=3, noise=-1)


# ---------------------------------------------------------------- global mode (the default)
def test_global_mode_recovers_one_uniform_scale_from_noise_free_data() -> None:
    p = project()
    y = truth_peaks(p, LIB, {"lifting": 1.25, "tools": 1.25, "drying": 1.25})
    r = calibrate(p, LIB, y, trials=200, seed=1)  # default mode is global
    assert r.mode == "global"
    assert all(v == pytest.approx(1.25, rel=0.01) for v in r.scales.values())
    assert r.improved and r.after.mae < 1e-6 < r.before.mae
    assert r.not_identifiable == []


def test_global_mode_improves_held_out_error_when_the_library_is_uniformly_off() -> None:
    p = project()
    y = truth_peaks(
        p, LIB, {"lifting": 1.2, "tools": 1.3, "drying": 1.25}
    )  # roughly uniform, not exact
    r = calibrate(p, LIB, y, trials=200, seed=3)
    assert r.improved and r.after.mae < 0.5 * r.before.mae
    assert not any("did not" in w for w in r.warnings)


def test_a_calibration_that_does_not_help_says_so_and_says_not_to_apply_it() -> None:
    p = project()
    y = truth_peaks(p, LIB, {})  # the model is already exact, nothing to improve
    r = calibrate(p, LIB, y, trials=100, seed=1)
    assert not r.improved
    assert any("do not apply" in w.lower() for w in r.warnings)


def test_category_mode_warns_when_there_are_too_few_weeks_for_the_scales_fitted() -> None:
    p = project()
    y = truth_peaks(p, LIB, {"tools": 1.2})
    r = calibrate(p, LIB, y, mode="category", trials=100, seed=1)
    assert any("too few" in w.lower() for w in r.warnings)


def test_global_scale_at_a_bound_is_flagged() -> None:
    p = project()
    y = truth_peaks(p, LIB, {"lifting": 3.0, "tools": 3.0, "drying": 3.0}) * 1.0
    r = calibrate(p, LIB, y, trials=100, seed=1)
    assert r.at_bound and any("bound" in w.lower() for w in r.warnings)


def test_nothing_to_fit_against_when_no_equipment_is_on_site_in_the_fitting_weeks() -> None:
    p = Project("p", 20, (Booking("crane", 1, 16, 19),), base_load_kw=5.0)
    with pytest.raises(CalibrationError, match="no equipment"):
        calibrate(p, LIB, np.full(20, 5.0), trials=50, seed=1)


def test_held_out_weeks_are_flagged_when_there_are_very_few() -> None:
    p = project(8)
    y = truth_peaks(p, LIB, {"tools": 1.2})
    r = calibrate(p, LIB, y, trials=100, seed=1)  # 8 weeks -> 5 train, 3 test
    assert r.test_weeks == [5, 6, 7]
    y2 = y.copy()
    y2[0:1] = np.nan  # 7 data weeks -> 4 train, 3 test
    r2 = calibrate(p, LIB, y2, trials=100, seed=1)
    assert len(r2.test_weeks) == 3
    p6 = project(6)
    r3 = calibrate(p6, LIB, truth_peaks(p6, LIB, {"tools": 1.2}), trials=100, seed=1)
    assert len(r3.test_weeks) == 2 and any("held-out" in w.lower() for w in r3.warnings)


def test_invalid_mode_is_rejected() -> None:
    p = project()
    with pytest.raises(CalibrationError, match="mode"):
        calibrate(p, LIB, truth_peaks(p, LIB, {}), mode="nonsense")  # type: ignore[arg-type]
