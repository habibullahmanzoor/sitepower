"""The look-and-feel module: valid output, safe against injected text, no NaN in drawn numbers."""

import math
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import style


def numbers_in(svg: str) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+\.\d+|-?\d+", svg)]


def test_css_is_balanced_and_covers_the_main_widgets() -> None:
    css = style.CSS
    assert css.count("{") == css.count("}")
    assert css.strip().startswith("<style>") and css.strip().endswith("</style>")
    for needle in ("stMetric", "stSidebar", "sp-hero", "stHeading", "stDataFrame", "stButton"):
        assert needle in css


def test_sparkline_is_valid_and_has_only_finite_numbers() -> None:
    svg = style.sparkline_svg([1, 2, 3, 2], [2, 3, 4, 3], [3, 4, 5, 4], peak_index=2)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert all(math.isfinite(n) for n in numbers_in(svg))
    assert "polyline" in svg and "polygon" in svg and "circle" in svg


@pytest.mark.parametrize(
    "p10,p50,p90",
    [([5.0], [5.0], [5.0]), ([0, 0, 0], [0, 0, 0], [0, 0, 0]), ([2, 2], [2, 2], [2, 2])],
)
def test_sparkline_handles_flat_single_and_all_zero_series(p10, p50, p90) -> None:
    svg = style.sparkline_svg(p10, p50, p90, peak_index=0)
    assert all(math.isfinite(n) for n in numbers_in(svg))


def test_sparkline_rejects_mismatched_or_empty_input() -> None:
    with pytest.raises(ValueError):
        style.sparkline_svg([1, 2], [1], [1, 2], 0)
    with pytest.raises(ValueError):
        style.sparkline_svg([], [], [], 0)


def test_hero_escapes_user_supplied_text() -> None:
    nasty = '<script>alert("x")</script> & "quoted"'
    html = style.hero_html(nasty, 24, "<svg></svg>", illustrative=True)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "illustrative" in html.lower()
    assert "Power</h1>" in html
    assert (
        style.hero_html("Real job", 10, "<svg></svg>", illustrative=False)
        .lower()
        .count("illustrative data")
        == 0
    )


def test_category_colour_is_stable_and_has_a_fallback() -> None:
    assert style.category_colour("lifting") == style.category_colour("lifting")
    assert style.category_colour("something new").startswith("#")
    assert style.category_colour("Base load") != style.category_colour("lifting")
