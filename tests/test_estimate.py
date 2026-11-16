"""Golden tests for the deterministic estimate. Every expected value is worked by hand in the comment above it."""

import numpy as np
import pytest

from sitepower.estimate import UnknownEquipmentError, estimate
from sitepower.models import Booking, Equipment, Project


def eq(
    id_: str = "a",
    kw: float = 10.0,
    pf: float = 0.8,
    lf: tuple[float, float, float] = (0.4, 0.6, 0.9),
    group: str | None = None,
) -> Equipment:
    return Equipment(
        id=id_,
        name=id_,
        category="test",
        rated_kw=kw,
        power_factor=pf,
        load_factor_min=lf[0],
        load_factor_mode=lf[1],
        load_factor_max=lf[2],
        diversity_group=group,
    )


def proj(bookings: list[Booking], weeks: int = 8, **kw: object) -> Project:
    return Project(name="t", weeks=weeks, bookings=tuple(bookings), **kw)  # type: ignore[arg-type]


def test_single_item_golden() -> None:
    # 1 x 10 kW at load factor 0.6 -> 6.0 kW; kVA = 6.0 / 0.8 = 7.5; booked weeks 2..4 only.
    e = estimate(proj([Booking("a", 1, 2, 4)]), {"a": eq()})
    assert e.kw.tolist() == pytest.approx([0, 0, 6, 6, 6, 0, 0, 0])
    assert e.kva.tolist() == pytest.approx([0, 0, 7.5, 7.5, 7.5, 0, 0, 0])


def test_quantity_multiplies() -> None:
    # 3 x 10 kW x 0.6 = 18.0 kW
    e = estimate(proj([Booking("a", 3, 0, 0)]), {"a": eq()})
    assert e.kw[0] == pytest.approx(18.0)


def test_group_diversity_golden() -> None:
    # Group "g": (10 x 0.6 = 6) + (10 kW x lf 0.4 = 4) = 10 kW, x diversity 0.7 = 7.0 kW.
    lib = {"a": eq("a", group="g"), "b": eq("b", lf=(0.4, 0.4, 0.4), group="g")}
    p = proj([Booking("a", 1, 0, 0), Booking("b", 1, 0, 0)], group_diversity={"g": 0.7})
    e = estimate(p, lib)
    assert e.kw[0] == pytest.approx(7.0)
    # kVA: (6/0.8 + 4/0.8) = 12.5, x 0.7 = 8.75
    assert e.kva[0] == pytest.approx(8.75)


def test_ungrouped_items_get_no_diversity() -> None:
    p = proj([Booking("a", 1, 0, 0)], group_diversity={"g": 0.5})
    assert estimate(p, {"a": eq()}).kw[0] == pytest.approx(6.0)


def test_group_without_declared_diversity_defaults_to_one() -> None:
    assert estimate(proj([Booking("a", 1, 0, 0)]), {"a": eq(group="g")}).kw[0] == pytest.approx(6.0)


def test_base_load_applies_every_week() -> None:
    # Base 5 kW at pf 0.9 -> 5.556 kVA, in every week including weeks with no bookings.
    p = proj([Booking("a", 1, 3, 3)], weeks=5, base_load_kw=5.0, base_power_factor=0.9)
    e = estimate(p, {"a": eq()})
    assert e.kw.tolist() == pytest.approx([5, 5, 5, 11, 5])
    assert e.kva[0] == pytest.approx(5 / 0.9)
    assert e.kva[3] == pytest.approx(5 / 0.9 + 7.5)


def test_overlapping_bookings_of_same_item_add() -> None:
    # 1 unit weeks 0..2 and 2 units weeks 2..3 -> week 2 has 3 units = 18 kW.
    p = proj([Booking("a", 1, 0, 2), Booking("a", 2, 2, 3)], weeks=4)
    assert estimate(p, {"a": eq()}).kw.tolist() == pytest.approx([6, 6, 18, 12])


def test_load_factor_override_changes_result() -> None:
    e = estimate(proj([Booking("a", 1, 0, 0)]), {"a": eq()}, load_factors={"a": 0.9})
    assert e.kw[0] == pytest.approx(9.0)


def test_lines_make_the_estimate_traceable() -> None:
    p = proj([Booking("a", 2, 1, 1)], weeks=3)
    e = estimate(p, {"a": eq()})
    assert e.lines[0] == ()
    (line,) = e.lines[1]
    assert (line.equipment_id, line.qty) == ("a", 2)
    assert line.kw == pytest.approx(12.0)
    assert line.kva == pytest.approx(15.0)
    assert line.diversity == 1.0


def test_unknown_equipment_is_a_clear_error() -> None:
    with pytest.raises(UnknownEquipmentError, match="nope"):
        estimate(proj([Booking("nope", 1, 0, 0)]), {"a": eq()})


def test_demand_never_decreases_with_quantity_and_is_never_negative_or_nan() -> None:
    prev = -1.0
    for qty in range(1, 12):
        e = estimate(proj([Booking("a", qty, 0, 3)]), {"a": eq()})
        assert np.isfinite(e.kw).all() and np.isfinite(e.kva).all()
        assert (e.kw >= 0).all() and (e.kva >= 0).all()
        assert e.kw[0] >= prev
        prev = float(e.kw[0])


def test_kva_is_never_below_kw() -> None:
    for pf in (0.5, 0.7, 0.95, 1.0):
        e = estimate(proj([Booking("a", 2, 0, 5)]), {"a": eq(pf=pf)})
        assert (e.kva >= e.kw - 1e-12).all()
