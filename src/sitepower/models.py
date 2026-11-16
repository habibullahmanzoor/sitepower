"""Plain, validated data types. Invalid values raise ValueError with a message that names the field."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


def _finite(name: str, v: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{name} must be a finite number")
    return float(v)


@dataclass(frozen=True)
class RowError:
    """A problem with one row of an imported file. `row` is the 1-based line number."""

    row: int
    message: str


@dataclass(frozen=True)
class Equipment:
    """One item in the equipment library.

    Load factors describe the fraction of `rated_kw` actually drawn while the item is in use,
    as a triangular distribution (min, mode, max). All figures are user data: the bundled
    library is illustrative only.
    """

    id: str
    name: str
    category: str
    rated_kw: float
    power_factor: float
    load_factor_min: float
    load_factor_mode: float
    load_factor_max: float
    diversity_group: str | None = None
    source: str = "illustrative"

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("id must not be empty")
        if _finite("rated_kw", self.rated_kw) <= 0:
            raise ValueError("rated_kw must be a positive number")
        if not 0 < _finite("power_factor", self.power_factor) <= 1:
            raise ValueError("power_factor must be above 0 and at most 1")
        lo = _finite("load_factor_min", self.load_factor_min)
        mode = _finite("load_factor_mode", self.load_factor_mode)
        hi = _finite("load_factor_max", self.load_factor_max)
        if not 0 < lo <= mode <= hi <= 1:
            raise ValueError(
                "load factors must satisfy 0 < load_factor_min <= load_factor_mode <= load_factor_max <= 1"
            )


@dataclass(frozen=True)
class Booking:
    """`qty` units of one equipment item on site for weeks `start_week` to `end_week` inclusive (0-based)."""

    equipment_id: str
    qty: int
    start_week: int
    end_week: int

    def __post_init__(self) -> None:
        if isinstance(self.qty, bool) or not isinstance(self.qty, int) or self.qty < 1:
            raise ValueError("qty must be a whole number of at least 1")
        if self.start_week < 0:
            raise ValueError("start_week must not be negative")
        if self.end_week < self.start_week:
            raise ValueError("end_week must not be before start_week")


@dataclass(frozen=True)
class Project:
    """A project: a number of weeks, equipment bookings and the user's diversity assumptions."""

    name: str
    weeks: int
    bookings: tuple[Booking, ...]
    group_diversity: Mapping[str, float] = field(default_factory=dict)
    base_load_kw: float = 0.0
    base_power_factor: float = 0.9

    def __post_init__(self) -> None:
        if isinstance(self.weeks, bool) or not isinstance(self.weeks, int) or self.weeks < 1:
            raise ValueError("weeks must be a whole number of at least 1")
        for b in self.bookings:
            if b.end_week >= self.weeks:
                raise ValueError(
                    f"booking of '{b.equipment_id}' ends in week {b.end_week}, outside a {self.weeks}-week project"
                )
        for g, f in self.group_diversity.items():
            if not 0 < _finite("diversity factor", f) <= 1:
                raise ValueError(
                    f"diversity factor {f} for group '{g}' must be above 0 and at most 1"
                )
        if _finite("base_load_kw", self.base_load_kw) < 0:
            raise ValueError("base_load_kw must not be negative")
        if not 0 < _finite("base_power_factor", self.base_power_factor) <= 1:
            raise ValueError("base_power_factor must be above 0 and at most 1")


@dataclass(frozen=True)
class WeekLine:
    """One booking's contribution in one week, before group diversity (`diversity` is the factor applied after)."""

    equipment_id: str
    qty: int
    kw: float
    kva: float
    diversity: float


@dataclass(frozen=True, eq=False)
class Estimate:
    """Weekly demand. `kw` and `kva` are arrays of length `weeks`; `lines[w]` explains week `w`."""

    kw: FloatArray
    kva: FloatArray
    lines: tuple[tuple[WeekLine, ...], ...]
