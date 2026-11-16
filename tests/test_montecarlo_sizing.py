"""Golden and property tests for uncertainty and sizing. Expected values are derived by hand in the comments."""

import numpy as np
import pytest

from sitepower.estimate import estimate
from sitepower.models import Booking, Equipment, Project
from sitepower.montecarlo import peak_percentile, simulate
from sitepower.sizing import ILLUSTRATIVE_SIZES_KVA, recommend_size


def eq(id_: str, lf: tuple[float, float, float], kw: float = 10.0, pf: float = 0.8) -> Equipment:
    return Equipment(
        id=id_,
        name=id_,
        category="t",
        rated_kw=kw,
        power_factor=pf,
        load_factor_min=lf[0],
        load_factor_mode=lf[1],
        load_factor_max=lf[2],
    )


def proj(*bookings: Booking, weeks: int = 6, **kw: object) -> Project:
    return Project("t", weeks, tuple(bookings), **kw)  # type: ignore[arg-type]


def test_zero_width_distribution_equals_the_deterministic_estimate_exactly() -> None:
    lib = {"a": eq("a", (0.6, 0.6, 0.6)), "b": eq("b", (0.5, 0.5, 0.5), kw=4)}
    p = proj(Booking("a", 2, 1, 3), Booking("b", 1, 2, 5), base_load_kw=3.0)
    det = estimate(p, lib)
    r = simulate(p, lib, trials=50, seed=1)
    for arr, want in (
        (r.p10_kw, det.kw),
        (r.p50_kw, det.kw),
        (r.p90_kw, det.kw),
        (r.p10_kva, det.kva),
        (r.p50_kva, det.kva),
        (r.p90_kva, det.kva),
    ):
        assert arr.tolist() == pytest.approx(want.tolist(), abs=1e-12)


def test_same_seed_gives_identical_results_and_different_seed_differs() -> None:
    lib = {"a": eq("a", (0.2, 0.5, 0.9))}
    p = proj(Booking("a", 3, 0, 5))
    a, b, c = simulate(p, lib, 500, 7), simulate(p, lib, 500, 7), simulate(p, lib, 500, 8)
    assert np.array_equal(a.peak_kw, b.peak_kw) and np.array_equal(a.p90_kw, b.p90_kw)
    assert not np.array_equal(a.peak_kw, c.peak_kw)


def test_sample_mean_matches_the_triangular_mean() -> None:
    # Triangular mean = (min + mode + max) / 3 = (0.2 + 0.5 + 0.9) / 3 = 0.5333...
    # 1 x 10 kW item -> mean demand 5.333 kW. Tolerance 1 % over 20 000 trials.
    lib = {"a": eq("a", (0.2, 0.5, 0.9))}
    r = simulate(proj(Booking("a", 1, 0, 0), weeks=1), lib, 20_000, 3)
    assert float(r.peak_kw.mean()) == pytest.approx(10 * (0.2 + 0.5 + 0.9) / 3, rel=0.01)


def test_percentiles_are_ordered_and_bracket_the_deterministic_value_sensibly() -> None:
    lib = {"a": eq("a", (0.2, 0.5, 0.9)), "b": eq("b", (0.3, 0.4, 0.8), kw=25)}
    p = proj(Booking("a", 2, 0, 5), Booking("b", 1, 2, 4), base_load_kw=2.0)
    r = simulate(p, lib, 1000, 5)
    assert (r.p10_kw <= r.p50_kw).all() and (r.p50_kw <= r.p90_kw).all()
    assert (r.p10_kva <= r.p50_kva).all() and (r.p50_kva <= r.p90_kva).all()
    assert (r.p10_kw < r.p90_kw)[2]  # a genuinely uncertain week has a real band
    assert (r.p90_kva >= r.p90_kw - 1e-9).all()


def test_weeks_with_only_base_load_have_no_uncertainty() -> None:
    lib = {"a": eq("a", (0.2, 0.5, 0.9))}
    r = simulate(proj(Booking("a", 1, 4, 4), base_load_kw=6.0), lib, 300, 2)
    assert r.p10_kw[0] == r.p90_kw[0] == pytest.approx(6.0)


def test_peak_week_counts_cover_every_trial() -> None:
    lib = {"a": eq("a", (0.2, 0.5, 0.9))}
    r = simulate(proj(Booking("a", 1, 2, 3)), lib, 400, 4)
    assert int(r.peak_week_counts.sum()) == 400
    assert set(np.flatnonzero(r.peak_week_counts)) <= {2, 3}
    assert len(r.peak_week_counts) == 6


def test_unused_library_items_do_not_change_the_result() -> None:
    lib1 = {"a": eq("a", (0.2, 0.5, 0.9))}
    lib2 = {**lib1, "zzz": eq("zzz", (0.1, 0.2, 0.3))}
    p = proj(Booking("a", 2, 0, 5))
    assert np.array_equal(simulate(p, lib1, 200, 9).peak_kw, simulate(p, lib2, 200, 9).peak_kw)


def test_more_equipment_never_lowers_the_p50_peak() -> None:
    lib = {"a": eq("a", (0.2, 0.5, 0.9))}
    prev = 0.0
    for qty in range(1, 8):
        r = simulate(proj(Booking("a", qty, 0, 5)), lib, 300, 11)
        cur = peak_percentile(r.peak_kw, 50)
        assert cur >= prev
        prev = cur


def test_simulate_validates_its_inputs() -> None:
    lib = {"a": eq("a", (0.2, 0.5, 0.9))}
    with pytest.raises(ValueError, match="trials"):
        simulate(proj(Booking("a", 1, 0, 0)), lib, 0, 1)
    with pytest.raises(ValueError, match="unknown equipment"):
        simulate(proj(Booking("nope", 1, 0, 0)), lib, 10, 1)
    with pytest.raises(ValueError, match="percentile"):
        peak_percentile(np.array([1.0, 2.0]), 150)


def test_no_nan_or_negative_values_for_valid_input() -> None:
    lib = {"a": eq("a", (0.05, 0.5, 1.0), pf=0.5)}
    r = simulate(proj(Booking("a", 4, 0, 5), base_load_kw=1.0), lib, 500, 6)
    for arr in (r.p10_kw, r.p50_kw, r.p90_kw, r.p10_kva, r.p90_kva, r.peak_kw, r.peak_kva):
        assert np.isfinite(arr).all() and (arr >= 0).all()


def test_sizing_golden() -> None:
    # 180 kVA x (1 + 0.15) = 207 kVA -> smallest listed size at or above 207.
    s = recommend_size(180.0, headroom=0.15)
    assert s.required_kva == pytest.approx(207.0)
    assert s.recommended_kva == min(x for x in ILLUSTRATIVE_SIZES_KVA if x >= 207)
    assert recommend_size(100.0, headroom=0.0).recommended_kva == 100


def test_sizing_edges_and_monotonicity() -> None:
    assert recommend_size(1e9).recommended_kva is None
    assert "exceeds" in recommend_size(1e9).note.lower()
    prev = 0.0
    # 860 x 1.15 = 989 kVA, still within the largest listed size
    for peak in np.linspace(1, 860, 60):
        rec = recommend_size(float(peak)).recommended_kva
        assert rec is not None and rec >= prev
        prev = rec
    with pytest.raises(ValueError):
        recommend_size(-1)
    with pytest.raises(ValueError):
        recommend_size(10, headroom=-0.1)
    with pytest.raises(ValueError):
        recommend_size(10, sizes=())
