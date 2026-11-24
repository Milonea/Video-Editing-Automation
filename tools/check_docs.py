from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def main() -> int:
    failures: list[str] = []
    for document in sorted(ROOT.rglob("*.md")):
        if any(part in {".git", "node_modules", ".venv"} for part in document.parts):
            continue
        source = document.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(source):
            target = target.strip().strip("<>")
            if not target or target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            local_target = unquote(target.split("#", 1)[0])
            if not local_target:
                continue
            resolved = (document.parent / local_target).resolve()
            if not resolved.exists() or ROOT not in resolved.parents and resolved != ROOT:
                failures.append(f"{document.relative_to(ROOT).as_posix()}: missing or out-of-repository link {target}")
    if failures:
        print("documentation links: FAIL")
        print("\n".join(f"- {failure}" for failure in failures))
        return 1
    print("documentation links: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
