# macOS 개발 안내

## 목적

macOS는 Python/JavaScript 공통 코드 작성, Schema 검증, 단위 테스트, 문서 작업과 가벼운 미디어 전처리를 위한 기준 개발 환경입니다. Apple Silicon M2·8GB RAM은 설계 참고점일 뿐 최소 요구사양이나 성능 보장값이 아닙니다.

## 현재 저장소에서 가능한 작업

Python 3.11 이상과 Node.js 20 이상으로 엔진·계약·Recipe 및 UXP 순수 로직 테스트를 실행할 수 있습니다. 기본 개발 설치에는 Whisper 모델, CUDA 또는 대형 미디어 데이터가 포함되지 않습니다. 가벼운 설정은 `vea inspect ... --profile lightweight`처럼 선택합니다.

`engine/scripts/install-macos.sh`도 기본으로 pytest와 엔진만 설치합니다. Whisper runtime이 필요한 경우에만 `--with-whisper`를 전달합니다. FFmpeg/FFprobe가 없으면 코드 검사와 단위 테스트는 계속 가능하지만 미디어 명령은 실행되지 않습니다.

```bash
python -m pip install -r requirements-dev.txt
python tools/validate_contracts.py
python -m pytest engine/tests -q
python -m unittest discover -s packages/python/tests -v
npm test
```

## 아직 이 안내만으로 사용할 수 없는 기능

Apple Silicon 실측, Intel Mac, 8GB 메모리 사용량과 실제 전처리는 `PENDING_HOST_VALIDATION`입니다. Whisper 실행 시 모델 다운로드와 메모리 요구가 발생할 수 있으므로 기본 개발 설치에서 선택 설치로 분리되어 있습니다.

저장소와 가상환경은 내장 저장장치에 두고 영상 프로젝트는 [외부 Workspace 안내](EXTERNAL_WORKSPACE.md)에 따라 분리하도록 설계합니다.
