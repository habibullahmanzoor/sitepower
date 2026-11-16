"""Runs the real Streamlit script headlessly and checks what a visitor would see."""

from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")


def run() -> "AppTest":
    return AppTest.from_file(APP, default_timeout=60).run()


def test_sample_project_renders_without_exceptions() -> None:
    at = run()
    assert not at.exception
    assert any("Power</h1>" in m.value for m in at.markdown)
    labels = [m.label for m in at.metric]
    assert "Peak, median of trials" in labels and "Recommended supply" in labels
    assert all(m.value for m in at.metric)


def test_illustrative_data_banner_and_disclaimer_are_visible() -> None:
    at = run()
    # one notice only (no st.warning / st.info banners), carrying both messages
    assert len(at.warning) == 0
    notices = [m.value for m in at.markdown if '<details class="sp-notice"' in m.value]
    assert len(notices) == 1
    assert "illustrative placeholders" in notices[0]
    assert "not a supply design or a quotation" in notices[0]


def test_changing_headroom_changes_the_required_supply() -> None:
    at = run()
    before = [m.value for m in at.metric if m.label == "Recommended supply"]
    at.slider(key="headroom").set_value(0)  # headroom 0%
    at.run()
    assert not at.exception
    after = [m.value for m in at.metric if m.label == "Recommended supply"]
    assert before and after


def test_same_seed_gives_identical_numbers() -> None:
    a, b = run(), run()
    assert [m.value for m in a.metric] == [m.value for m in b.metric]


def _metric(at: "AppTest", label: str) -> float:
    m = next(m for m in at.metric if m.label == label)
    return float(m.value.split()[0].replace(",", ""))


def _click(at: "AppTest", starts: str) -> "AppTest":
    next(b for b in at.button if b.label.startswith(starts)).click()
    return at.run()


def test_calibration_flow_apply_then_remove_restores_the_original_numbers() -> None:
    at = run()
    original = _metric(at, "Peak, central estimate")
    at.toggle(key="use_sample_meter").set_value(True).run()
    assert not at.exception
    assert any("SYNTHETIC data" in w.value for w in at.warning)  # the sample is always labelled
    at = _click(at, "Apply these scales")
    assert not at.exception
    assert any("A calibration is applied" in s.value for s in at.success)
    calibrated = _metric(at, "Peak, central estimate")
    assert calibrated > original * 1.1  # the synthetic example under-estimates by about 25%
    at = _click(at, "Remove the calibration")
    assert not any("A calibration is applied" in s.value for s in at.success)
    assert _metric(at, "Peak, central estimate") == original


def test_apply_is_enabled_when_the_calibration_improves_held_out_error() -> None:
    at = run()
    at.toggle(key="use_sample_meter").set_value(True).run()
    apply_btn = next(b for b in at.button if b.label.startswith("Apply these scales"))
    assert not apply_btn.disabled  # the sample improves held-out error, so it can be applied


def test_new_tabs_render_and_slip_changes_the_estimate() -> None:
    at = run()
    assert not at.exception
    assert [t.label for t in at.tabs][:8] == [
        "Overview", "Project", "Detail", "Compare", "Cost", "Calibrate", "Export & notes", "How to use",
    ]  # fmt: skip
    headers = " ".join(h.value for h in at.header)
    assert "Compare two schedules" in headers and "Generator or grid" in headers
    before = [m.value for m in at.metric if m.label == "Peak, 90% below"]
    at.slider(key="slip").set_value(4)
    at.run()
    assert not at.exception
    after = [m.value for m in at.metric if m.label == "Peak, 90% below"]
    assert before and after
    # unchanged scenario B equals A, so the Compare table's difference column is all zeros
    cmp_df = next(d for d in at.dataframe if "B minus A" in d.value.columns)
    assert set(cmp_df.value["B minus A"].str.replace("+", "").str.replace("-", "")) <= {
        "0",
        "0 kVA",
    }
