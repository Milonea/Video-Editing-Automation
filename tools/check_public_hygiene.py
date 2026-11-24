from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_EXTENSIONS = {
    ".mp4", ".mov", ".mxf", ".mkv", ".avi", ".webm", ".wav", ".mp3", ".m4a", ".aac", ".flac",
    ".prproj", ".aep", ".mogrt", ".ccx", ".psd", ".ai"
}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]
PRIVATE_PATH_PATTERNS = [
    re.compile(r"(?i)\b[A-Z]:[/\\]" + "Users[/\\]" + r"[^/\\\s]+"),
    re.compile(r"/" + "Users/" + r"[^/\s]+"),
    re.compile(r"/" + "home/" + r"[^/\s]+"),
]


def files_to_check() -> list[Path]:
    return sorted(
        path for path in ROOT.rglob("*")
        if path.is_file() and not any(part in {".git", "node_modules", ".venv", "venv"} for part in path.parts)
    )


def main() -> int:
    failures: list[str] = []
    for path in files_to_check():
        relative = path.relative_to(ROOT).as_posix()
        if path.is_symlink():
            failures.append(f"symbolic link is not allowed: {relative}")
            continue
        if path.suffix.casefold() in FORBIDDEN_EXTENSIONS:
            failures.append(f"media or editor project file is not allowed: {relative}")
            continue
        if path.stat().st_size > 50 * 1024 * 1024:
            failures.append(f"file exceeds 50 MiB: {relative}")
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except OSError as error:
            failures.append(f"could not read {relative}: {type(error).__name__}")
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                failures.append(f"possible credential material in {relative}")
                break
        for pattern in PRIVATE_PATH_PATTERNS:
            if pattern.search(content):
                failures.append(f"possible user-specific absolute path in {relative}")
                break
    if failures:
        print("public hygiene: FAIL")
        print("\n".join(f"- {failure}" for failure in failures))
        return 1
    print(f"public hygiene: PASS ({len(files_to_check())} files inspected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
