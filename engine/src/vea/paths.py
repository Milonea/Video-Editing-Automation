from __future__ import annotations

import os
import unicodedata
from pathlib import Path


def normalize_path(path: str | Path) -> str:
    """Resolve a local path and normalize its Unicode spelling for portable records."""
    resolved = str(Path(path).expanduser().resolve())
    return unicodedata.normalize("NFC", resolved)


def same_path(left: str | Path, right: str | Path) -> bool:
    left_path = os.path.normcase(normalize_path(left).replace("\\", "/"))
    right_path = os.path.normcase(normalize_path(right).replace("\\", "/"))
    return left_path == right_path


def same_recorded_path(left: str, right: str) -> bool:
    """Compare stored paths independent of slash and Unicode normalization."""
    left_key = unicodedata.normalize("NFC", left.replace("\\", "/")).casefold()
    right_key = unicodedata.normalize("NFC", right.replace("\\", "/")).casefold()
    return left_key == right_key
