# macOS 개발 안내

## 목적

macOS는 Python/JavaScript 공통 코드 작성, Schema 검증, 단위 테스트, 문서 작업과 가벼운 미디어 전처리를 위한 기준 개발 환경입니다. Apple Silicon M2·8GB RAM은 설계 참고점일 뿐 최소 요구사양이나 성능 보장값이 아닙니다.

## 현재 저장소에서 가능한 작업

Python 3.11 이상과 Node.js 20 이상으로 계약 테스트를 실행할 수 있습니다. 기본 검사에는 Whisper 모델, CUDA, 대형 미디어 데이터 또는 Premiere가 필요하지 않습니다.

```bash
python -m pip install -r requirements-dev.txt
python tools/validate_contracts.py
python -m unittest discover -s packages/python/tests -v
npm test
```

## 아직 이 안내만으로 사용할 수 없는 기능

미디어 엔진, CLI, CFR 변환, 전사 및 Premiere 패널은 공개 저장소에 아직 이전되지 않았습니다. 따라서 이 문서는 해당 기능의 설치·실행을 안내하지 않습니다. Apple Silicon 실측, Intel Mac, 메모리 사용량과 실제 전처리는 `PENDING_HOST_VALIDATION`입니다.

저장소와 가상환경은 내장 저장장치에 두고 영상 프로젝트는 [외부 Workspace 안내](EXTERNAL_WORKSPACE.md)에 따라 분리하도록 설계합니다.
