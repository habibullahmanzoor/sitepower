"""Turn a peak kVA into a recommended supply size.

`ILLUSTRATIVE_SIZES_KVA` is a PLACEHOLDER list (TODO(verify)): real supplier offerings differ by
region, voltage and connection type. Replace it with the supplier's actual options. The result is a
planning figure, never a quotation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

ILLUSTRATIVE_SIZES_KVA: tuple[float, ...] = (
    25, 50, 63, 100, 150, 200, 250, 315, 400, 500, 630, 800, 1000,
)  # fmt: skip


@dataclass(frozen=True)
class SizingResult:
    peak_kva: float
    headroom: float
    required_kva: float
    recommended_kva: float | None
    note: str


def recommend_size(
    peak_kva: float,
    headroom: float = 0.15,
    sizes: Sequence[float] = ILLUSTRATIVE_SIZES_KVA,
) -> SizingResult:
    """required = peak x (1 + headroom); recommend the smallest listed size at or above it."""
    if not math.isfinite(peak_kva) or peak_kva < 0:
        raise ValueError("peak_kva must be a finite number, zero or more")
    if not math.isfinite(headroom) or headroom < 0:
        raise ValueError("headroom must be a finite number, zero or more")
    if len(sizes) == 0:
        raise ValueError("sizes must not be empty")
    required = peak_kva * (1 + headroom)
    fits = sorted(s for s in sizes if s >= required)
    if not fits:
        return SizingResult(
            peak_kva, headroom, required, None,
            f"Required {required:.0f} kVA exceeds the largest listed size ({max(sizes):.0f} kVA).",
        )  # fmt: skip
    chosen = fits[0]
    return SizingResult(
        peak_kva, headroom, required, chosen,
        f"Smallest listed size at or above {required:.0f} kVA (illustrative list; confirm with the supplier).",
    )  # fmt: skip
