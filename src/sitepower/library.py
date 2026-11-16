"""Equipment library: CSV in, validated Equipment out, with row-numbered errors.

Required columns: id, name, category, rated_kw, power_factor, load_factor_min, load_factor_mode,
load_factor_max. Optional: diversity_group, source. A bad row is reported and skipped; other rows load.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from sitepower.models import Equipment, RowError

REQUIRED = (
    "id",
    "name",
    "category",
    "rated_kw",
    "power_factor",
    "load_factor_min",
    "load_factor_mode",
    "load_factor_max",
)


@dataclass
class EquipmentParse:
    library: dict[str, Equipment] = field(default_factory=dict)
    errors: list[RowError] = field(default_factory=list)


def _num(row: dict[str, str], key: str) -> float:
    raw = (row.get(key) or "").strip()
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{key} must be a number (got '{raw}')") from None


def parse_equipment_csv(text: str) -> EquipmentParse:
    out = EquipmentParse()
    text = text.lstrip("﻿")
    if text.strip() == "":
        out.errors.append(RowError(1, "File is empty."))
        return out
    reader = csv.DictReader(io.StringIO(text))
    names = [n.strip() for n in (reader.fieldnames or [])]
    reader.fieldnames = names
    missing = [c for c in REQUIRED if c not in names]
    if missing:
        out.errors.append(RowError(1, f"Missing column(s): {', '.join(missing)}."))
        return out
    for row in reader:
        line = reader.line_num
        try:
            e = Equipment(
                id=(row.get("id") or "").strip(),
                name=(row.get("name") or "").strip(),
                category=(row.get("category") or "").strip(),
                rated_kw=_num(row, "rated_kw"),
                power_factor=_num(row, "power_factor"),
                load_factor_min=_num(row, "load_factor_min"),
                load_factor_mode=_num(row, "load_factor_mode"),
                load_factor_max=_num(row, "load_factor_max"),
                diversity_group=(row.get("diversity_group") or "").strip() or None,
                source=(row.get("source") or "").strip() or "unspecified",
            )
        except ValueError as exc:
            out.errors.append(RowError(line, str(exc)))
            continue
        if e.id in out.library:
            out.errors.append(RowError(line, f"duplicate id '{e.id}' (first row kept)"))
            continue
        out.library[e.id] = e
    return out


def find_library_path(data_dir: Path) -> Path:
    """`equipment.local.csv` (the user's real figures, git-ignored) wins over the illustrative file."""
    local = data_dir / "equipment.local.csv"
    return local if local.exists() else data_dir / "equipment.illustrative.csv"


def is_illustrative(path: Path) -> bool:
    return path.name != "equipment.local.csv"
