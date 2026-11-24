from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TEXT = {
    "AGENTS.md": ["Use a task branch and pull request", "Do not force-push", "Never use a merge fallback to bypass a failed or unavailable check"],
    ".codex/PR_POLICY.md": ["A security, credential, access-control, privacy, or data-loss risk is unresolved", "Never treat missing check data as success"],
    ".codex/WORKFLOW.md": ["Never merge a stale head", "required CI checks"],
    ".codex/PROJECT_PROFILE.md": ["원본 미디어·기존 시퀀스의 덮어쓰기/삭제 금지", "최종 프로젝트 라이선스는 미정"],
}


def main() -> int:
    failures: list[str] = []
    for relative, phrases in REQUIRED_TEXT.items():
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"required project policy is missing: {relative}")
            continue
        content = path.read_text(encoding="utf-8")
        for phrase in phrases:
            if phrase not in content:
                failures.append(f"required policy boundary is absent from {relative}")
    if failures:
        print("policy integrity: FAIL")
        print("\n".join(f"- {failure}" for failure in failures))
        return 1
    print("policy integrity: PASS (repository workflow, merge gates, and project data boundaries retained)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
