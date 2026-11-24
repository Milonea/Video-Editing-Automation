# Migration Matrix

## 조사 기준

| 저장소 | 조사 기준 기본 브랜치 SHA | 파일/디렉터리 수 | 발견 사항 |
| --- | --- | ---: | --- |
| `Milonea/Video-Edit-Agent` | `8f4d75845ac9496d1bc07f3a371651a1251b93e5` | 99 files / 19 directories | `LICENSE`는 MIT지만 `pyproject.toml`의 패키지 라이선스 필드는 `Proprietary`로 표시 |
| `Milonea/automation_VESupport` | `5e2070d4aef0e26171a9e3ab50130f6cb499e1a7` | 222 files / 56 directories | 저장소 `LICENSE` 없음. 저장소 트리에 MOGRT, 특정 콘텐츠 DB, 아이콘과 음원 자산 포함 |
| `Milonea/Video-Editing-Automation` | `04f5040a6eb038f14a40e3d80733c242297e505d` | 8 files / 2 directories | 기본 템플릿만 존재. 기존 열린 PR 없음. 기본 브랜치 보호 정보 endpoint는 현재 연결에서 읽기 불가 |

원본 파일은 조회만 했고 수정하지 않았습니다. 대상 기본 브랜치의 AGENTS, PR 정책, 개발 Workflow, CI 설정 템플릿, PR 템플릿은 그대로 보존합니다. 구현 코드를 옮기기 전 권리 기준을 해소해야 하므로 아래 표의 원본 이식 항목은 현재 공개 브랜치에 복사하지 않았습니다.

## 기능별 매핑

| 기존 기능·위치 | 대상 위치 | 분류 / 상태 | 이전·검증 기준 |
| --- | --- | --- | --- |
| VEA `src/vea/cli.py`, 미디어·타임라인·오디오·자막·체크포인트 모듈 | `engine/` | **공개 전 차단** | MIT LICENSE와 Proprietary 패키지 메타데이터 충돌 해결 후 이전. CLI 회귀·합성 미디어·시간축 테스트 필요 |
| VEA `src/vea/workspace.py`, `config.py`, `paths.py`, `config/` | `engine/`, `config/` | **범용화 후 계승 예정 / 공개 전 차단** | 사용자 전용 manifest 이름과 `owner_persona` 제거, 상대경로·Workspace ID·기존 포맷 이전 계약 검증 |
| VEA `src/vea/silence_split.py`, `adobe/vea-silence-review/**` | `engine/`, `integrations/premiere/uxp/` | **공개 전 차단** | 원본 라이선스 충돌 해소 후 Smart Silence 계산과 패널을 연결. 실제 Premiere 분할은 호스트 검증 전까지 Pending |
| VEA `transcriber.py`, `cfr.py`, `audio.py`, Windows 실행 스크립트 | `engine/`, `scripts/` | **공개 전 차단** | 선택 의존성·CPU/CUDA capability, VFR/CFR 시간 매핑과 재개 검증 필요. MLX 실행은 원본 기준 미구현 |
| VEA Codex Noa 설정·스킬·개인 운영 문서 | `agents/` | **개인 확장으로 분리** | 사용자 Persona를 복사하지 않음. 역할/입력/출력만 AgentTask·AgentResult 계약으로 재구성 |
| VESupport `Automation/lib/host-operation-contract.js`, `premiere-service.js`, `project-item-cache.js`, UXP 패널 | `integrations/premiere/` | **권리 확인 전 보류** | 저장소 라이선스 부재. 공통 동작은 승인된 코드만 이전하거나 사용자 요구사항에서 새 구현. Premiere 호스트 테스트 필수 |
| VESupport `M3_Automation/lib/**`, `M3_Automation/schemas/**` | `contracts/`, `recipes/`, `integrations/` | **인터페이스만 신규 정의** | 이번 Schema/Fixture는 사용자 명세를 기반으로 새 작성. 원본 소스 구현을 복사하지 않음. Recipe 컴파일러는 미구현 |
| VESupport `Automation/data/**`, `Automation/modules/**`, `Automation/assets/**` | 비공개 Extension 저장소 | **공개 코어에서 제외** | 콘텐츠별 DB, 이미지, 효과음, MOGRT는 필수 의존성으로 올리지 않음. 재배포 권한과 개인 확장 분리 확인 전 제외 |
| VESupport `packages/CEP_M3_Move_Standalone/**`, `ae_automation/**` | 선택적 레거시 어댑터 | **권리/지원 상태 확인 후 결정** | Adobe SDK/CEP, JSX 및 After Effects 실제 버전·라이선스 확인 필요. 이번 PR에서 복사하지 않음 |
| 대상 저장소 템플릿 `.codex/*`, `.github/*`, `AGENTS.md` | 동일 경로 | **그대로 계승** | 정책과 검증 지침 유지. 제품 README와 프로젝트별 프로필만 작성 |
| 사용자 요구사항의 공통 데이터 계약 | `contracts/schemas/`, `contracts/examples/`, `packages/` | **신규 구현** | 27개 Schema 정의, 합성 Fixture, Python JSON Schema 검사, JavaScript 안전 검사; 단위 테스트 실행 |

## 기능 상태 분류

- **그대로 계승:** 템플릿의 AGENTS, PR 운영 정책, CI 설정 체크리스트와 Workflow 파일.
- **범용화 후 계승:** 미디어 엔진, Workspace, Premiere 실행 흐름. 라이선스 충돌 해소 후 진행.
- **중복 기능 통합:** Python 편집 계획과 JavaScript 편집 adapter는 공통 Timeline/Plan 계약으로 연결할 예정.
- **인터페이스만 계승:** Recipe, Extension, Agent 계약은 사용자 요구사항에 맞춰 새로 정의했습니다.
- **개인 확장팩으로 분리:** 콘텐츠 DB, MOGRT, 사용자 Persona와 외부 자산.
- **레거시 호환 계층 후보:** JSX, CEP 및 기존 Workspace 문서 형식. 호스트와 권리 확인 전 미지원.
- **공개 금지/보류:** 실제 제작 미디어, 권리 미확인 템플릿·아이콘·음원, 토큰과 사용자별 경로.
- **미구현:** 미디어 실행 엔진, Recipe 실행, UXP 통합 패널, Premiere XML/타임라인 검증.
