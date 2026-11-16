"""Schedule slip, peak drivers, phases, cost comparison and the HTML report. Expected values worked by hand."""

import numpy as np
import pytest

from sitepower.analysis import compare_costs, energy_kwh, peak_drivers, phase_summary
from sitepower.estimate import estimate
from sitepower.models import Booking, Equipment, Project
from sitepower.montecarlo import simulate
from sitepower.report import report_html
from sitepower.uimodel import headline


def eq(id_: str, kw: float = 10.0, lf: float = 0.5, group: str | None = None) -> Equipment:
    return Equipment(id_, id_, "t", kw, 1.0, lf, lf, lf, group)


LIB = {"a": eq("a"), "b": eq("b", kw=20.0)}


def proj(*bookings: Booking, weeks: int = 6) -> Project:
    return Project("t", weeks, tuple(bookings))


def test_zero_slip_is_identical_to_no_slip_argument() -> None:
    p = proj(Booking("a", 1, 0, 2), Booking("b", 1, 1, 4))
    x, y = simulate(p, LIB, 300, 3), simulate(p, LIB, 300, 3, slip_weeks=0)
    assert np.array_equal(x.p90_kw, y.p90_kw)


def test_slip_never_adds_energy_and_is_reproducible() -> None:
    # a 3-week booking of 5 kW in an 8-week project; delays of 0..2 weeks never push it out of the window
    p = proj(Booking("a", 1, 0, 2), weeks=8)
    s1, s2 = simulate(p, LIB, 400, 9, slip_weeks=2), simulate(p, LIB, 400, 9, slip_weeks=2)
    assert np.array_equal(s1.p50_kw, s2.p50_kw)
    base = simulate(p, LIB, 400, 9)
    # fixed load factor 0.5 -> 5 kW whenever the item is on site; the slip trials' peak is still 5 kW
    assert s1.peak_kw.max() == pytest.approx(5.0)
    assert base.peak_kw.max() == pytest.approx(5.0)
    # slipping spreads the item over weeks 1..5, so week 1 (index 0) is on in fewer trials: P90 there is lower
    assert s1.p90_kw[0] <= base.p90_kw[0]
    assert s1.p90_kw[4] >= base.p90_kw[4]  # week 5 is only ever on when delayed


def test_slip_pushed_past_the_end_is_dropped() -> None:
    p = proj(Booking("a", 1, 3, 3), weeks=4)  # on site in week 4 only; any delay drops it
    s = simulate(p, LIB, 600, 1, slip_weeks=3)
    assert s.peak_kw.max() == pytest.approx(5.0)
    assert (s.peak_kw == 0).any()  # some trials never have it on site


def test_bad_slip_rejected() -> None:
    with pytest.raises(ValueError):
        simulate(proj(Booking("a", 1, 0, 0)), LIB, 10, 0, slip_weeks=-1)


def test_peak_drivers_sorted_with_cumulative_share() -> None:
    # week 1: a = 1 x 10 x 0.5 = 5 kW, b = 1 x 20 x 0.5 = 10 kW -> b 66.7%, a 33.3%
    p = proj(Booking("a", 1, 0, 1), Booking("b", 1, 0, 1))
    det = estimate(p, LIB)
    d = peak_drivers(det, 1, LIB, {})
    assert [x.equipment_id for x in d] == ["b", "a"]
    assert d[0].kw == pytest.approx(10.0)
    assert d[0].share == pytest.approx(2 / 3)
    assert d[-1].cumulative == pytest.approx(1.0)
    with pytest.raises(ValueError):
        peak_drivers(det, 99, LIB, {})


def test_peak_drivers_apply_group_diversity() -> None:
    lib = {"a": eq("a", group="g")}
    p = Project("t", 2, (Booking("a", 2, 0, 1),), {"g": 0.5})
    d = peak_drivers(estimate(p, lib), 1, lib, p.group_diversity)
    assert d[0].kw == pytest.approx(5.0)  # 2 x 10 x 0.5 x 0.5


def test_phase_summary() -> None:
    p = proj(Booking("a", 1, 0, 1), Booking("b", 1, 2, 3), weeks=4)
    det = estimate(p, LIB)  # kW by week: 5, 5, 10, 10
    p90 = det.kva
    res, problems = phase_summary(
        [("early", 1, 2), ("late", 3, 4), ("bad", 3, 9), ("", 0, 1)], det, p90
    )
    assert [r.name for r in res] == ["early", "late"]
    assert res[0].peak_kw == 5 and res[1].peak_kw == 10 and res[1].peak_week == 3
    assert len(problems) == 2 and "phase 4" in problems[1]


def test_energy_and_costs_by_hand() -> None:
    kw = np.array([10.0, 10.0, 30.0])
    assert energy_kwh(kw, 40) == pytest.approx(50 * 40)
    # weekly kWh = 400, 400, 1200. Grid: 1000 connection + 0.2/kWh -> 1080, 1160, 1400.
    # Generator: 100/week + 0.5/kWh -> 300, 600, 1300 cumulative.
    r = compare_costs(kw, 40, 1000, 0.2, 100, 0.5)
    assert r.grid_total == pytest.approx(1400)
    assert r.generator_total == pytest.approx(1300)
    assert r.cheaper == "generator" and r.saving == pytest.approx(100)
    assert r.breakeven_week is None  # generator never passes grid inside the project
    r2 = compare_costs(kw, 40, 0, 0.2, 100, 0.5)  # grid 80, 160, 400 vs gen 300, 600, 1300
    assert r2.cheaper == "grid" and r2.breakeven_week == 1


def test_cost_inputs_validated() -> None:
    with pytest.raises(ValueError):
        compare_costs(np.array([1.0]), 40, -1, 0.2, 1, 1)
    with pytest.raises(ValueError):
        compare_costs(np.array([1.0]), 200, 1, 0.2, 1, 1)
    with pytest.raises(ValueError):
        energy_kwh(np.array([1.0]), float("nan"))


def test_report_is_escaped_and_complete() -> None:
    p = proj(Booking("a", 1, 0, 2))
    det, mc = estimate(p, LIB), simulate(p, LIB, 200, 0)
    out = report_html(
        "<script>alert(1)</script>", det, mc, headline(det, mc, 0.15), ["a & b"], True
    )
    assert "<script>alert" not in out and "&lt;script&gt;" in out
    assert "a &amp; b" in out and "illustrative placeholders" in out
    assert out.count("<tr>") == 1 + 6  # header + one row per week


def test_pdf_is_wellformed_and_paginates() -> None:
    import re

    from sitepower.pdf import report_pdf

    p = proj(Booking("a", 1, 0, 2))
    det, mc = estimate(p, LIB), simulate(p, LIB, 200, 0)
    head = headline(det, mc, 0.15)
    out = report_pdf("Site (A) \\ <b>", det, mc, head, ["x (y)"], True)
    assert out.startswith(b"%PDF-1.4") and out.rstrip().endswith(b"%%EOF")
    start = int(re.search(rb"startxref\n(\d+)", out).group(1))  # type: ignore[union-attr]
    assert out[start : start + 4] == b"xref"
    for m in re.finditer(rb"(\d{10}) 00000 n", out):  # every offset points at an object header
        assert re.match(rb"\d+ 0 obj", out[int(m.group(1)) :])
    assert out.count(b"/Type /Page ") == 1
    long_p = Project("t", 150, (Booking("a", 1, 0, 149),))
    ld, lm = estimate(long_p, LIB), simulate(long_p, LIB, 50, 0)
    longer = report_pdf("t", ld, lm, headline(ld, lm, 0.15), [], False)
    assert longer.count(b"/Type /Page ") >= 2
