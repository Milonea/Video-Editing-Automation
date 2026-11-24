#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 이상을 설치한 뒤 다시 실행하세요." >&2
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 이상이 필요합니다.")
PY

EXTRAS="[dev]"
if [ "${1:-}" = "--with-whisper" ]; then
  EXTRAS="[macos,dev]"
elif [ "$#" -gt 0 ]; then
  echo "사용법: $0 [--with-whisper]" >&2
  exit 2
fi

python3 -m venv --copies .venv-macos
.venv-macos/bin/python -m pip install -e ".$EXTRAS"
.venv-macos/bin/vea doctor

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "FFmpeg/FFprobe가 없습니다. 코드 검사와 단위 테스트는 가능하지만 미디어 처리는 별도 설치가 필요합니다." >&2
fi
echo "macOS 가상환경: $PROJECT_DIR/.venv-macos"
echo "활성화: source \"$PROJECT_DIR/.venv-macos/bin/activate\""
