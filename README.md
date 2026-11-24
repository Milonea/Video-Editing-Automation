# Video Editing Automation (VEA)

Video Editing Automation은 영상 분석 엔진과 편집기 자동화를 공통 데이터 계약으로 연결하는 범용 프레임워크입니다. 저장소는 MIT License로 배포합니다. 원본 미디어, 개인 프로젝트, 직접 제작·수정하는 이미지·음원·MOGRT와 로컬 확장팩은 사용자 Workspace에 두며 공개 저장소에 포함하지 않습니다.

## 현재 구현 상태

이번 마이그레이션은 기존 VEA의 Python 미디어 엔진과 Smart Silence 검토용 Premiere UXP 패널, automation_VESupport의 범용 Timeline Plan·Recipe 검사기와 Premiere 실행 안전 모듈을 가져옵니다. 개인화된 Workspace 이름과 Persona 필드는 제거하거나 일반화했고, 대상 저장소의 AGENTS/PR/CI 운영 템플릿을 보존합니다.

| 영역 | 상태 |
| --- | --- |
| 공통 JSON Schema와 Python/JavaScript 계약 검사 | 구현 및 CI 검증 |
| vea CLI, Workspace Resolver, 미디어 분석·전사·자막·러프컷·체크포인트 | 코드 이전 및 자동 회귀 테스트 |
| Smart Silence 계산 및 Premiere UXP 검토 패널 | 코드 이전 및 단위 테스트; 설치·분할 동작은 실제 호스트 재검증 대기 |
| 범용 Timeline Plan, Recipe, 이미지/자막 편집 계획기 | 코드 이전 및 Node.js 회귀 테스트; 공통 프레임 기반 Schema 연결은 추가 통합 작업 |
| Premiere Preflight·Dry-run·승인 게이트 공통 모듈 | 코드 이전 및 Mock 테스트; 실제 UXP Adapter 미통합 |
| 로컬 제작 이미지·음원·MOGRT, 콘텐츠 DB, 고정 콘텐츠 UI | 공개 저장소에서 제외; 사용자 로컬 Workspace/확장팩에서 관리 |
| Windows/Premiere 프로덕션, macOS 성능, CUDA/외장 Workspace 교차 검증 | 실제 환경 검증 대기 |

CI 통과는 실제 Premiere·GPU·Apple Silicon·외장 SSD 검증을 뜻하지 않습니다. 세부 상태는 기능 지원표, Migration Matrix, 검증 보고서를 확인하세요.

## 빠른 시작

Python 3.11 이상과 Node.js 20 이상을 설치합니다. 기본 개발 의존성은 미디어 모델이나 GPU 런타임을 설치하지 않습니다.

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e ./engine
python tools/validate_contracts.py
python -m pytest engine/tests -q
npm test
```

FFmpeg와 FFprobe는 미디어 기능 실행 시 별도 설치가 필요합니다. Whisper는 선택 의존성이므로 필요한 환경에서만 설치합니다.

```bash
python -m pip install -e './engine[macos]'
# Windows CUDA 프로필은 실제 CUDA 런타임 요구사항을 확인한 뒤 설치
python -m pip install -e './engine[windows]'
```

기존 CLI 명령 vea는 호환성 때문에 유지합니다. 설치 세부 내용은 엔진 안내를 참고하세요.

## 개발 및 운영 원칙

- macOS를 코드 개발과 경량 전처리의 우선 환경으로 고려하고, Windows를 실제 제작과 Premiere 통합의 우선 검증 환경으로 둡니다.
- 공통 코어는 Python·JavaScript와 운영체제를 강제 통일하지 않고 Schema/Adapter 경계로 연결합니다.
- 편집 계획은 미리보기와 Preflight 후 명시적 승인 없이 실행하지 않습니다.
- 원본 미디어와 기존 시퀀스를 보존하며 충돌 클립을 자동 삭제하지 않습니다.
- 소스와 가상환경은 각 기기의 내장 SSD에 두고, 영상 프로젝트와 로컬 제작 자산은 외장 SSD 또는 사용자 지정 Workspace에 둡니다.
- 로컬 이미지·음원·MOGRT와 Persistent Token은 Git에 추가하지 않습니다.

설정과 교차 운영은 크로스플랫폼 개발 안내, 외부 Workspace 안내, Premiere 연동 안내에서 확인할 수 있습니다.

## 기여 및 변경 관리

대상 저장소 템플릿과 PR/브랜치 규칙은 AGENTS.md와 .codex/WORKFLOW.md를 따릅니다. 작업 순서는 ToDo.md, 실제 구현 변경은 CHANGELOG.md에 기록합니다. 기존 비공개 저장소의 Git history와 원본 미디어는 이 저장소에 포함하지 않았습니다.
