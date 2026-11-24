from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vea.repo_hygiene import audit_repository_entries  # noqa: E402


def tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or "git ls-files failed")
    return sorted({os.fsdecode(item) for item in result.stdout.split(b"\0") if item})


def main() -> int:
    try:
        paths = tracked_paths(ROOT)
    except (OSError, RuntimeError) as exc:
        print(f"repository hygiene: ERROR ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 2
    entries = []
    for relative in paths:
        path = ROOT / relative
        try:
            if path.is_symlink():
                entries.append((relative, -1))
            elif path.is_file():
                entries.append((relative, path.stat().st_size))
            else:
                entries.append((relative, None))
        except OSError:
            entries.append((relative, None))
    failures = audit_repository_entries(entries)
    if failures:
        print("repository hygiene: FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"repository hygiene: PASS ({len(entries)} paths inspected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
