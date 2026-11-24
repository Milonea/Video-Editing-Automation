# 마이그레이션 보고서 — 초기 통합 단계

**기준일:** 2026-11-24 (KST)  
**결과:** PARTIAL — 계약 기반과 검증만 공개 브랜치에 준비. 엔진 및 Premiere 코드 이전은 라이선스 결정 전 차단.

## A. 작업 요약

대상 저장소 템플릿을 보존하고, 범용 계약 Schema·합성 Fixture·Python/JavaScript 검증 기반을 구현했습니다. 저장소는 아직 제작용 영상편집 도구가 아닙니다. 전체 원본 코드를 공개 저장소로 가져오거나 두 애플리케이션을 통합한 상태가 아닙니다.

## B. 기능별 이전 결과

각 파일별 출처, 계획 대상, 이전 방법 및 검증 기준은 [Migration Matrix](MIGRATION_MATRIX.md)에 기록했습니다. 이번 변경에서 실제 이식된 것은 새로 작성한 공통 계약 레이어입니다. 기존 엔진·UXP·JSX·데이터·자산은 공개 브랜치에 복사하지 않았습니다.

## C. 범용화 결과

- 콘텐츠 고유 데이터와 자산을 기본 실행 의존성으로 두지 않는 Manifest, Asset, Recipe, Extension 계약을 새로 정의했습니다.
- 개별 Persona 대신 Video Workflow Manager, Media Processing, Editing Automation, Quality Assurance, Release and Documentation 역할을 AgentTask/AgentResult로 정의했습니다.
- 기존 콘텐츠별 DB·MOGRT·효과음의 공개 이전은 권리 확인 전 차단했습니다. 현재 비공개 작업 환경을 공개 Extension으로 옮기지 않았습니다.

## D. 플랫폼별 검증 결과

| 대상 | 상태 |
| --- | --- |
| 공통 Python/JavaScript 계약 Fixture | 이 실행 환경에서 단위 테스트 통과 |
| macOS | 실제 Apple Silicon 검증 미수행 |
| Windows | 실제 사용자 시스템 검증 미수행 |
| Premiere UXP / JSX / XML | 실제 호스트 검증 미수행 |
| CPU/CUDA/MLX 전사 | 검증 미수행. GPU 존재만으로 지원 처리하지 않음 |
| 외장 Workspace의 OS 교차 사용 | 실제 외장 드라이브 검증 미수행 |

## E. 템플릿 보존 결과

`AGENTS.md`, `.codex/PR_POLICY.md`, `.codex/WORKFLOW.md`, `.codex/PROJECT_PROFILE.template.md`, `.github/CI_SETUP.template.md`, `.github/pull_request_template.md`를 유지합니다. README를 제품 안내로 바꾸고, CONTRIBUTING을 한국어·프로젝트 경계에 맞게 조정하며, `.codex/PROJECT_PROFILE.md`와 검증 Workflow를 추가합니다. 기존 정책을 약화시키는 변경은 없습니다.

## F. 안전 및 공개 검증

- 원본 두 저장소는 읽기 전용으로 조사했으며 대상 Git history에 포함하지 않았습니다.
- VEA `LICENSE`와 `pyproject.toml`의 상충하는 선언을 확인했고, VESupport 저장소의 `LICENSE` 부재를 확인했습니다.
- 실제 미디어, 프로젝트 파일, 콘텐츠 DB, MOGRT, 사용자 Persona와 외부 자산을 공개 변경에서 제외했습니다.
- 공개 저장소에 최종 배포 라이선스를 새로 지정하지 않았습니다.
- 공개 산출물 개인정보·Secret 검사 결과는 `docs/VALIDATION_REPORT.md`에서 기록합니다.

## G. GitHub 작업 결과

작업 브랜치, commit SHA, Pull Request URL과 hosted CI 결과는 이 보고서를 포함한 Pull Request에 표시합니다. 원본 저장소에는 변경을 수행하지 않습니다. 공개 PR은 라이선스·호스트 게이트가 남아 있는 동안 Draft로 유지합니다.

## H. 요구사항 일치 여부

| 요구사항 영역 | 상태 | 근거 |
| --- | --- | --- |
| 템플릿 보존 및 새 프로젝트 문서 | PARTIAL | 정책 파일 유지, 프로젝트 프로필·README·문서 작성 |
| 공통 Python/JavaScript Schema | PASS | 공통 Fixture 27종 검증 |
| Clean-history 공개 이식 | PARTIAL | 원본 Git history 미사용, 기존 구현 코드는 권리 게이트로 보류 |
| 미디어 엔진과 기존 CLI 보존 | BLOCKED | VEA 라이선스 선언 불일치 |
| Premiere UXP/JSX 통합 | BLOCKED | 편집기 원본 라이선스 부재 및 실제 호스트 미검증 |
| 개인 데이터·콘텐츠 종속성 제거 | PARTIAL | 신규 코드/Fixture는 합성 데이터만 사용, 원본 자산은 미이전 |
| Extension/Recipe 실행 | PARTIAL | 선언형 계약만 구현, 로더·실행기는 미구현 |
| Cross-platform 원본 프로젝트 처리 | PENDING_VALIDATION | 플랫폼 문서와 계약 기초만 있음 |
| 비파괴 Preflight 및 복구 | PARTIAL | 계약에서 승인·원본 보존 원칙 강제, 실행기 미구현 |
| 실제 Premiere 및 GPU 검증 | PENDING_VALIDATION | 현재 환경에서 수행 불가 |
| 최종 릴리스 준비 | NOT_IMPLEMENTED | 코드 이전·호스트 검증·라이선스 결정 전 |

## I. 사용자 후속 작업

1. VEA 코드의 실제 권리 조건을 확정해 `MIT`와 `Proprietary` 중 어느 선언이 유효한지 결정합니다.
2. 편집기 자동화 코드 및 포함된 Adobe/외부 자산의 공개·재배포 권한을 확인하고 저장소 라이선스 정책을 결정합니다.
3. 이후 별도 Windows 환경에서 Premiere UXP/JSX, MOGRT, XML, 외장 Workspace 교차 사용과 GPU backend를 검증합니다.
4. 이 PR의 변경 범위와 미완료 항목을 검토합니다.
