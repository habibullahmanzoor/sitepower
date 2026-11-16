import csv
import io
from pathlib import Path

import numpy as np
import pytest

from sitepower.estimate import estimate
from sitepower.io import profile_to_csv, project_from_json
from sitepower.library import find_library_path, is_illustrative, parse_equipment_csv
from sitepower.montecarlo import simulate

DATA = Path(__file__).resolve().parent.parent / "data"


def load_sample():
    lib = parse_equipment_csv((DATA / "equipment.illustrative.csv").read_text(encoding="utf-8"))
    project = project_from_json((DATA / "sample_project.json").read_text(encoding="utf-8"))
    return lib, project


def test_bundled_library_is_valid_and_labelled_illustrative() -> None:
    lib, _ = load_sample()
    assert lib.errors == []
    assert len(lib.library) >= 10
    assert all("ILLUSTRATIVE" in e.source for e in lib.library.values())


def test_sample_project_only_uses_known_equipment_and_runs() -> None:
    lib, project = load_sample()
    assert {b.equipment_id for b in project.bookings} <= set(lib.library)
    e = estimate(project, lib.library)
    assert e.kw.shape == (project.weeks,) and np.isfinite(e.kw).all()
    assert e.kw.max() > e.kw[0] > 0  # the build-up is visible and the base load never vanishes


def test_sample_project_week_21_matches_an_independent_hand_calculation() -> None:
    # Worked by hand from the CSV and JSON, not by calling the library:
    # welfare (6 + 9) x 0.8 = 12.0 | lighting (14.4 + 25.5) x 0.95 = 37.905 | lifting 7.7 x 0.85 = 6.545
    # tools 8 x 0.6 = 4.8 | drying (10.8 + 36) x 0.9 = 42.12 | hvac 60 x 0.5 = 30 (no group) | base 3
    lib, project = load_sample()
    det = estimate(project, lib.library)
    assert det.kw[20] == pytest.approx(12.0 + 37.905 + 6.545 + 4.8 + 42.12 + 30.0 + 3.0)
    assert det.kw[20] == pytest.approx(136.37)
    assert int(np.argmax(det.kw)) == 20  # week 21 is the central-estimate peak


def test_local_library_overrides_the_illustrative_one(tmp_path: Path) -> None:
    (tmp_path / "equipment.illustrative.csv").write_text("x", encoding="utf-8")
    assert find_library_path(tmp_path).name == "equipment.illustrative.csv"
    assert is_illustrative(find_library_path(tmp_path))
    (tmp_path / "equipment.local.csv").write_text("x", encoding="utf-8")
    assert find_library_path(tmp_path).name == "equipment.local.csv"
    assert not is_illustrative(find_library_path(tmp_path))


def test_profile_csv_has_one_row_per_week_with_all_columns() -> None:
    lib, project = load_sample()
    det = estimate(project, lib.library)
    mc = simulate(project, lib.library, 200, 1)
    rows = list(csv.DictReader(io.StringIO(profile_to_csv(project, det, mc))))
    assert len(rows) == project.weeks
    assert list(rows[0]) == [
        "week", "kw_deterministic", "kva_deterministic",
        "kw_p10", "kw_p50", "kw_p90", "kva_p10", "kva_p50", "kva_p90",
    ]  # fmt: skip
    assert rows[0]["week"] == "1"
    assert float(rows[5]["kw_deterministic"]) == pytest.approx(det.kw[5], abs=5e-4)
    assert float(rows[5]["kw_p10"]) <= float(rows[5]["kw_p90"])


def test_sample_metered_file_parses_is_labelled_synthetic_and_calibrates_honestly() -> None:
    from datetime import date

    from sitepower.calibrate import calibrate, parse_metered_csv, weekly_peaks

    lib, project = load_sample()
    text = (DATA / "sample_metered.synthetic.csv").read_text(encoding="utf-8")
    assert text.startswith("# SYNTHETIC DATA")
    parsed = parse_metered_csv(text)
    assert parsed.errors == [] and len(parsed.samples) == 16 * 7 * 48
    peaks = weekly_peaks(parsed.samples, date(2025, 1, 6), project.weeks)
    assert int(np.isfinite(peaks).sum()) == 16  # the first 16 of 24 weeks are metered
    r = calibrate(project, lib.library, peaks, trials=300, seed=0)
    assert r.improved and r.after.mae < 0.25 * r.before.mae
    assert 1.15 < next(iter(r.scales.values())) < 1.30  # the library was generated about 25 % low
    assert not r.warnings
