"""The static-site build: everything the in-browser app needs is copied, nothing private is."""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_site  # noqa: E402


def test_build_copies_the_app_library_and_data_and_writes_an_index(tmp_path: Path) -> None:
    out = tmp_path / "site"
    files = build_site.build(ROOT, out)
    assert "app/streamlit_app.py" in files and "app/style.py" in files
    assert "src/sitepower/estimate.py" in files and "src/sitepower/calibrate.py" in files
    assert (
        "data/equipment.illustrative.csv" in files and "data/sample_metered.synthetic.csv" in files
    )
    for rel in files:
        assert (out / rel).is_file()
    assert (out / ".nojekyll").is_file()
    assert (out / "index.html").is_file()


def test_the_users_local_equipment_file_is_never_copied(tmp_path: Path) -> None:
    fake_root = tmp_path / "proj"
    for rel in ("app", "src/sitepower", "data"):
        (fake_root / rel).mkdir(parents=True)
    (fake_root / "app/streamlit_app.py").write_text("x", encoding="utf-8")
    (fake_root / "app/style.py").write_text("x", encoding="utf-8")
    (fake_root / "src/sitepower/__init__.py").write_text("x", encoding="utf-8")
    (fake_root / "src/sitepower/__pycache__").mkdir()
    (fake_root / "src/sitepower/__pycache__/a.pyc").write_bytes(b"x")
    for name in (
        "equipment.illustrative.csv",
        "sample_project.json",
        "sample_metered.synthetic.csv",
    ):
        (fake_root / "data" / name).write_text("x", encoding="utf-8")
    (fake_root / "data/equipment.local.csv").write_text("SECRET REAL FIGURES", encoding="utf-8")
    out = tmp_path / "site"
    files = build_site.build(fake_root, out)
    assert not any("local" in f for f in files)
    assert not any(f.endswith(".pyc") for f in files)
    assert not (out / "data/equipment.local.csv").exists()
    assert "SECRET" not in (out / "index.html").read_text(encoding="utf-8")


def test_index_pins_the_stlite_version_and_lists_exactly_the_copied_files(tmp_path: Path) -> None:
    out = tmp_path / "site"
    files = build_site.build(ROOT, out)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert f"@stlite/browser@{build_site.STLITE_VERSION}/build/stlite.js" in html
    assert re.fullmatch(r"\d+\.\d+\.\d+", build_site.STLITE_VERSION)  # pinned, never "latest"
    block = re.search(r"const FILES = (\[.*?\]);", html, re.S)
    assert block is not None
    assert sorted(json.loads(block.group(1))) == sorted(files)
    assert 'entrypoint: "app/streamlit_app.py"' in html


def test_build_fails_loudly_when_a_required_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_site.build(tmp_path, tmp_path / "site")
