# 마이그레이션 보고서

**기준일:** 2026-11-24 (KST)  
**전체 결과:** PARTIAL — 핵심 엔진과 범용 편집 계획 코드를 이전하고 자동 검증했으나, Recipe 전체 action 통합과 실제 호스트 검증은 남아 있습니다.  
**프로덕션 릴리스:** 준비 완료 아님

## A. 작업 요약

두 원본 저장소에서 실제 코드·설정·테스트를 확인하고, 대상 저장소의 clean-history 작업 브랜치에 범용 기능을 가져왔습니다. 공개 프로젝트 코드에 MIT License를 적용하라는 사용자의 선택을 반영했습니다. 외부 이미지·음원·MOGRT, 콘텐츠 DB, 개인 프로젝트, 계정 정보와 Adobe SDK는 포함하지 않았습니다.

주요 디렉터리:

- engine/ — Python 미디어 엔진, CLI, 설정, Workspace, 테스트 및 설치 스크립트
- packages/javascript/editing-plans/ — legacy Timeline Plan/Recipe planner, 안전 편집 primitive, frame contract adapter, 합성 테스트
- integrations/premiere/uxp/silence-review/ — VEA Smart Silence review panel
- integrations/premiere/shared/ — Preflight·Dry-run·approval, error sanitizer, 프로젝트 캐시
- contracts/ — 언어 중립 JSON Schema와 합성 Fixture
- docs/ — 아키텍처, 마이그레이션, 플랫폼, Workspace, Recipe, 보안 및 검증 지침

원본 Git history는 사용하지 않았으며 대상 저장소 템플릿 파일은 보존했습니다.

## B. 기능별 이전 결과

| 기능 | 원본 | 대상 | 변경 및 검증 |
| --- | --- | --- | --- |
| 미디어 분석·타임코드·오디오·자막·전사·러프컷·XML·체크포인트 | Video-Edit-Agent의 src/vea/** | engine/src/vea/** | 주요 모듈·테스트 이전; 113 Python 회귀 테스트 PASS |
| 기존 CLI | Video-Edit-Agent의 vea CLI | engine 패키지의 vea 명령 | 명령 이름 유지; editable package 설치 PASS |
| Workspace Resolver | Video-Edit-Agent의 workspace/config/project | engine/src/vea 및 config | Workspace manifest 이름과 프로젝트 metadata 일반화; Workspace 테스트 통과 |
| Smart Silence 계산·UXP review panel | Video-Edit-Agent의 silence_split.py와 UXP panel | engine 및 integrations/premiere/uxp/silence-review | Node 테스트 통과; 실제 Premiere 재설치는 대기 |
| Timeline Plan/Recipe/safe primitive | automation_VESupport의 M3_Automation/lib | packages/javascript/editing-plans/lib | planner source와 tests 이전; fixture를 합성 일반 데이터로 변경 |
| Recipe seconds→frames adapter | 신규 migration seam | packages/javascript/editing-plans/legacy-contract-adapter.js | 프레임 정렬 action subset 변환; 무단 반올림·미지원 action 차단 |
| Preflight, asset resolution, partial result | automation_VESupport host-operation-contract | integrations/premiere/shared | 명시 승인 gate 추가; Mock 및 sanitization/cache 테스트 통과 |
| 고정 콘텐츠 UI/DB/MOGRT patcher | automation_VESupport Automation 및 assets | 공개 core 미포함 | 콘텐츠 고정 동작 제거; 범용 UI·host adapter는 후속 과제 |
| Adobe CEP/JSX/CSInterface | automation_VESupport 레거시 통합 | 미이전 | SDK 재배포·호스트 검증이 없어 제외 |

파일별 분류와 기준 SHA는 [Migration Matrix](MIGRATION_MATRIX.md)를 참조하세요.

## C. 범용화 결과

- 프로젝트 metadata의 특정 Persona owner field를 제거했습니다.
- Workspace manifest 이름을 사용자·개인 계정에 결합되지 않은 공통 이름으로 바꾸고 기존 로컬 파일 복사·검증 방법을 문서화했습니다.
- Recipe의 콘텐츠별 템플릿 action을 information template 개념으로 일반화했습니다.
- 테스트에서 특정 콘텐츠명·이미지명·DB 의존성을 합성 일반명으로 바꿨습니다.
- 사용자가 로컬에서 유지·수정하는 이미지·음원·MOGRT와 콘텐츠 DB, 글로서리, 확장팩은 Workspace/로컬 확장 경계 밖으로 올리지 않습니다.
- 고정 버튼과 콘텐츠별 설정, 특정 MOGRT UUID가 박힌 패처는 공개 코어에 가져오지 않았습니다. 필요한 동작은 선언형 Recipe/Extension으로 재구성할 수 있는 계약을 남겼습니다.

## D. 플랫폼별 검증 결과

| 환경 | 상태 |
| --- | --- |
| Linux 컨테이너 자동 테스트 | PASS — 공통 계약, 113 Python 엔진 테스트, 54 JavaScript 테스트 |
| macOS 개발 | 코드·설정·경량 profile 준비; Apple Silicon M2/8GB 실측 PENDING_VALIDATION |
| Windows 프로덕션 | 설치 스크립트·CUDA 선택 설정 이전; 사용자 Windows 시스템 실측 PENDING_VALIDATION |
| CPU/CUDA/MLX | CPU/CUDA 경로와 선택 의존성 이전; 실제 런타임 미검증. MLX는 미구현 |
| Premiere Pro UXP | 패널·순수 로직 이전; 현재 대상 브랜치의 Premiere host 검증 PENDING_VALIDATION |
| 외장 SSD 교차 Workspace | resolver 코드 이전; 두 OS 간 실제 이동·재개 PENDING_VALIDATION |

원본 패널 README의 과거 Windows Premiere Beta 실험 기록은 이번 브랜치의 실제 호스트 검증 완료로 계산하지 않습니다.

## E. 템플릿 보존 결과

유지한 템플릿: AGENTS.md, .codex/PR_POLICY.md, .codex/WORKFLOW.md, .codex/PROJECT_PROFILE.template.md, .github/CI_SETUP.template.md, .github/pull_request_template.md.

변경·추가: 프로젝트 README/CONTRIBUTING/CONCEPT/ToDo/CHANGELOG, .codex/PROJECT_PROFILE.md, GitHub validation workflow, MIT LICENSE와 migration/architecture/platform/security 문서. 변경 이유와 제약은 해당 문서에 기록했습니다. 정책 템플릿 파일을 삭제하거나 약화하지 않았습니다.

## F. 안전 및 공개 검증

- root MIT License를 적용했고 Python package metadata도 MIT로 일치시켰습니다.
- 원본 저장소에는 변경을 수행하지 않았습니다.
- 원본 commit history, 실제 영상, 자산 DB, 이미지·음원·MOGRT, 프로젝트 파일, credential과 Persistent Token을 대상 변경에서 제외했습니다.
- Adobe SDK/CSInterface와 content-bound MOGRT patcher/UI는 복사하지 않았습니다.
- 공개 Hygiene 검사 PASS: 147개 파일을 검사했습니다. 계약·문서·policy check도 PASS입니다.
- .gitignore에 로컬 이미지·음원·MOGRT·Workspace·개인 Extension 경계를 추가했습니다.
- 자동 검사 결과는 외부 자산 라이선스 인증이나 Premiere/OS 호스트 검증을 뜻하지 않습니다.

## G. GitHub 작업 결과

- 작업 브랜치: codex/vea-shared-contract-foundation
- Pull Request: [#1 — Video Editing Automation migration](https://github.com/Milonea/Video-Editing-Automation/pull/1), Draft
- 기존 foundation commit과 migration commit은 PR commit 목록에서 확인합니다.
- PR은 Draft로 유지합니다. 실제 Windows/Premiere/Apple Silicon/CUDA/외장 Workspace 검증과 사용자 리뷰가 남아 있습니다.
- 대상 저장소 main에 병합하지 않았고 branch protection/승인 정책을 우회하지 않았습니다.
- 새 migration commit의 GitHub Actions 결과는 push 후 PR Checks에서 확인합니다.

## H. 요구사항 일치 여부

| 요구사항 | 상태 | 실제 결과 |
| --- | --- | --- |
| 원본 저장소 조사와 기준 SHA 기록 | PASS | 두 원본 및 대상 기준 commit을 Migration Matrix에 기록 |
| Clean-history migration과 원본 read-only | PASS | 대상 작업 브랜치에서 파일만 이전, 원본 수정 없음 |
| MIT 라이선스 | PASS | 사용자가 MIT를 선택; root/package metadata 일치 |
| 대상 템플릿 및 정책 보존 | PASS | 정책 파일과 PR/CI 템플릿 유지 |
| VEA 핵심 Python 엔진/CLI 계승 | PASS | 코드·설정·테스트 이전, 113 Python tests PASS |
| VESupport 기능 범용화 | PARTIAL | generic planner/host safety 이전; 콘텐츠 고정 UI와 전체 adapter는 제외/후속 |
| 개인 Persona·콘텐츠 IP 분리 | PASS | core/test fixture에서 제거; 개인 자산은 local-only |
| 공통 Python/JavaScript contracts | PARTIAL | 공통 Schema/검사 및 정렬 Recipe adapter 있음; 모든 legacy action mapping은 미완료 |
| Recipe/Extension 시스템 | PARTIAL | planner와 안전 계약 이전; 등록 loader/sandbox/UI 미구현 |
| 설정 계층과 실행 profile | PASS | common→OS→profile→local→project→explicit→CLI 구현 및 테스트 |
| 외장 Workspace/macOS↔Windows 연속 작업 | PENDING_VALIDATION | resolver/config 이전; 실제 두 OS 교차 사용 미검증 |
| 비파괴 편집 및 승인 안전성 | PARTIAL | plan/safe primitive/host approval unit tests PASS; 실제 host 적용 검증 대기 |
| 자동 테스트와 문서화 | PASS | Python/JS/Schema/docs/hygiene/policy 로컬 PASS; hosted CI push 후 확인 |
| 개인정보·Secret·미디어 제외 | PASS | 공개 검사 PASS, 이번 변경에 콘텐츠 파일 없음 |
| Multi Agent Industry 독립성 | PASS | 필수 의존성이나 외부 인증 추가 없음 |
| 실제 Premiere/Windows/GPU/macOS 검증 | PENDING_VALIDATION | 현재 실행 환경에서 수행하지 않음 |
| 프로덕션 릴리스 준비 | NOT_IMPLEMENTED | 위 실제 호스트·교차 Workspace 검증 및 일부 계약 통합 필요 |

## I. 사용자 후속 작업

1. PR #1을 검토하고 대상 저장소 정책대로 승인/병합을 결정합니다.
2. Windows에서 합성 프로젝트로 Premiere UXP 설치, Preflight/승인 gate, Razor/review-copy, XML·오디오·자막 동기화와 작업 재개를 검증합니다.
3. 외장 SSD를 macOS와 Windows에서 차례로 열어 Workspace ID 재연결과 Unicode 경로를 확인합니다.
4. 실제 M2 8GB Mac에서 lightweight profile의 메모리와 전처리 시간을 확인합니다.

직접 제작한 이미지·음원·MOGRT는 계속 로컬 Workspace에 두면 됩니다. 공개 저장소에 업로드할 필요가 없습니다.
