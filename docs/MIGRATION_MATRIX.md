# Migration Matrix

## 조사 기준

| 저장소 | 작업 시작 시 기준 commit | 트리 규모 | 검토 메모 |
| --- | --- | ---: | --- |
| `Milonea/Video-Edit-Agent` | `8f4d75845ac9496d1bc07f3a371651a1251b93e5` | 99 files / 19 directories | root LICENSE는 MIT; 패키지 metadata의 Proprietary 선언은 대상 사본에서 MIT로 맞춤 |
| `Milonea/automation_VESupport` | `5e2070d4aef0e26171a9e3a37130f6cb499e1a7` | 222 files / 56 directories | root LICENSE 부재; 콘텐츠별 코드와 자산, Adobe SDK가 혼재 |
| `Milonea/Video-Editing-Automation` | `04f5040a6eb038f14a40e3d80733c242297e505d` | 8 files / 2 directories | 새 저장소 템플릿에서 작업 브랜치 생성 |

원본 저장소에는 변경을 수행하지 않았습니다. 대상 저장소는 원본 Git history 없이 작업 브랜치에서 변경합니다.

## 기능별 이전 결과

| 원본 기능 및 위치 | 대상 위치 | 분류 / 결과 | 변경 및 검증 기준 |
| --- | --- | --- | --- |
| VEA `src/vea/**`, CLI | `engine/src/vea/**` | 범용화 후 계승 — 이전 | `vea` CLI/API 유지; project persona field 제거; pytest 회귀 테스트 |
| VEA `config/**`, OS profiles | `engine/config/**` | 계승·확장 — 이전 | 공통/OS/profile/local/project/explicit/task 순서; 네 profile과 CLI 선택 옵션 |
| VEA `tests/**`, requirements, install scripts | `engine/tests/**`, `engine/scripts/**` | 테스트/실행환경 계승 | 개인 Persona 전용 test 제외; 기존 기능 회귀 검사 |
| VEA `adobe/vea-silence-review/**` | `integrations/premiere/uxp/silence-review/**` | Smart Silence 패널 계승 | 분할 안전 로직 및 Node 단위 테스트; 대상 브랜치 Premiere host 검증은 pending |
| VEA 개인 Agent/Persona/개인 운영 문서 | 공개 저장소 미포함 | 개인 확장으로 분리 | 역할 기반 Agent 계약만 유지; 개인 문자열/운영 설정 미이전 |
| VEA Workspace Resolver / manifest | `engine/src/vea/workspace.py`, `engine/config/**` | 범용화 후 계승 | 새 manifest 이름과 테스트로 사용자 개인 prefix 제거; 구 파일은 로컬에서 복사·재검증 안내 |
| VESupport `M3_Automation/lib/**` | `packages/javascript/editing-plans/lib/**` | 공통 기능 계승, legacy 호환 계층 | Recipe/Edit Plan/안전 primitive/자막·이미지·무음 계획기와 source tests 이전. 콘텐츠 용어를 일반화 |
| VESupport `M3_Automation/schemas/**`, fixtures/tests | `packages/javascript/editing-plans/schemas/**`, `tests/**` | legacy 계약/회귀 fixture 계승 | 콘텐츠 이름을 합성 일반명으로 바꿈; 명시 frame rate adapter가 정렬된 subset을 변환하고 안전하게 반올림하지 않음 |
| VESupport `Automation/lib/error-sanitizer.js`, `host-operation-contract.js`, `project-item-cache.js` | `integrations/premiere/shared/**` | 공통 안전 코드 계승 | Preflight 뒤 Dry-run 또는 명시 승인으로만 삽입; Node Mock 테스트 |
| VESupport 고정 UI, `premiere-service.js`, MOGRT patcher, 콘텐츠 config/DB | 공개 core 제외 | 범용 재구현 대상으로 분리 | 하드코딩 데이터/UUID/액션/자산 루트가 있어 복사하지 않음; 사용자는 자산을 로컬에 유지 |
| VESupport `Automation/assets/**`, 실제 DB, 이미지·음원·MOGRT | 공개 Git에 미포함 | 공개 제외 | 사용자가 직접 유지·수정하는 Workspace 자산; 실행 필수 의존성 아님 |
| VESupport CEP/JSX/After Effects 및 Adobe `CSInterface.js` | 미이전 | 권리/호스트 확인 대기 | 제3자 Adobe SDK와 호스트 호환성 검증 후 별도 결정 |
| 대상 `AGENTS.md`, `.codex/**`, `.github/**` 정책/템플릿 | 동일 경로 | 그대로 계승 | 정책 내용 보존; 제품 문서와 CI 검증만 추가 |
| 공개 대상 LICENSE | root `LICENSE` | MIT 선택 적용 | 사용자가 MIT를 명시 선택; 코드 metadata 일치; 개인·제3자 자산에는 적용하지 않음 |

## 기능별 상태 분류

- **그대로 계승:** 대상 저장소의 개발/PR 정책 템플릿, VEA CLI 이름과 핵심 API 계약.
- **범용화 후 계승:** VEA Workspace identity, project metadata, VESupport Recipe action과 합성 fixture.
- **중복 기능 통합:** Python Media Engine과 JavaScript Editing Plan은 공유 Schema에 연결 시작; legacy seconds-to-frames adapter는 정렬된 action subset만 지원.
- **인터페이스만 계승:** 콘텐츠별 UI 동작을 설명하는 공통 Recipe/Extension/Agent 계약.
- **개인 확장팩으로 분리:** 개인 Persona, 콘텐츠 DB, 고정 action 이름, MOGRT field UUID, 이미지·음원·개인 글로서리.
- **레거시 호환 계층으로 유지:** 기존 `vea` CLI 명령 및 초 단위 Recipe planner API; 안정적 공통 API 전환 전 legacy로 표시.
- **공개 금지/제외:** 사용자 Workspace 데이터, 직접 제작·수정하는 외부 자산, 계정정보, 개인 경로, 권리 미확인 Adobe SDK.
- **미구현 또는 추가 검증:** 완전한 Recipe action mapping, Extension loader/sandbox, 통합 UXP UI, JSX/CEP, Premiere/Windows/GPU/외장SSD 교차 검증.

## 디렉터리 선택 근거

기존 템플릿 구조를 유지하고 Python 엔진은 `engine/`, 공통 JavaScript 코드와 planner는 `packages/javascript/`, Premiere host 통합은 `integrations/premiere/`, 계약 Schema는 `contracts/`에 둡니다. 별도 콘텐츠 plugin이나 비어 있는 추상화 계층은 추가하지 않았습니다.
