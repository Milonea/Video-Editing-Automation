# VEA Media Engine

이 디렉터리는 Python 기반 미디어 분석·전처리 엔진입니다. `vea` CLI는 FFprobe/FFmpeg 탐색, 프로젝트 초기화, Workspace 확인, 타임코드와 편집 지시문 처리, 전사·자막, 비파괴 러프컷, Premiere 교환 XML, Smart Silence Split, 체크포인트 및 결과 보고 기능을 제공합니다.

## 설치

공통 설치는 Python 3.11 이상과 FFmpeg/FFprobe가 필요합니다. 개발 의존성은 저장소 루트에서 설치합니다.

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e ./engine
```

Whisper는 기본 설치에 포함하지 않습니다. 운영체제 프로필과 GPU 런타임을 확인한 뒤 필요한 선택 의존성만 설치합니다.

```bash
python -m pip install -e './engine[macos]'
# Windows CPU 전사
python -m pip install -e './engine[windows-cpu]'
# Windows CUDA 전사는 확인된 NVIDIA/CUDA 환경에서만 선택
python -m pip install -e './engine[windows]'
```

macOS 설치 스크립트는 기본적으로 개발 의존성만 설치하며 `--with-whisper`를 지정해야 Whisper를 추가합니다. Windows 스크립트도 기본 경량 설치를 사용하고 `-WithWhisper`, `-WithCuda` 옵션으로 전사 백엔드를 선택합니다.

## 안전 경계

- Workspace manifest 파일명은 `.vea-workspace.json`이며 영상 데이터는 코드 저장소 외부에 둡니다.
- 원본 미디어와 기존 편집 프로젝트를 자동으로 덮어쓰거나 삭제하지 않습니다.
- Smart Silence Split은 후보와 검증 정보를 별도 산출물로 남기고 자동 삭제하지 않습니다.
- `vea` CLI 이름은 이전 사용자 호환성을 위해 유지됩니다.
- Apple Silicon, CUDA, Premiere 및 XML 호스트 동작은 실제 환경 검증이 되기 전까지 지원 완료로 간주하지 않습니다.

기능별 현재 상태는 [`../docs/FEATURE_SUPPORT_MATRIX.md`](../docs/FEATURE_SUPPORT_MATRIX.md)를 기준으로 확인하세요.
