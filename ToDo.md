# 개발 현황

기능 상태의 기준은 [Feature Support Matrix](docs/FEATURE_SUPPORT_MATRIX.md), 변경 내역은 [CHANGELOG.md](CHANGELOG.md)입니다.

## Phase 0 — Discovery

- [x] 원본 두 곳과 대상의 기본 브랜치 commit SHA 기록
- [x] 대상 템플릿, 브랜치 및 Pull Request 상태 조사
- [x] VEA MIT LICENSE와 이전 pyproject metadata 상충 발견 및 대상 사본에서 조정
- [x] automation_VESupport의 콘텐츠별 코드/자산/Adobe SDK 조사
- [x] 프로젝트 코드 MIT 적용 사용자 결정 반영
- [x] 사용자 로컬 이미지·음원·MOGRT 공개 제외 정책 확인

## Phase 1 — Foundation

- [x] 공통 Schema v1과 합성 Fixture 정의
- [x] Python/JavaScript 계약 검사와 CI 추가
- [x] 개발 템플릿 및 운영 정책 보존
- [x] development/lightweight/production/validation profile과 우선순위 구현
- [x] 프레임 정렬 legacy Recipe action을 공통 EditPlan으로 변환하는 초기 adapter
- [ ] Python/JavaScript 공통 Recipe frame contract 전체 action으로 정착

## Phase 2 — Media Engine Migration

- [x] VEA 핵심 엔진·CLI·설정·테스트 이전
- [x] 사용자 Persona 필드와 Workspace 이름 범용화
- [x] Smart Silence 계산 및 UXP review panel 이전
- [ ] VEA 전체 회귀/CLI/합성 미디어 검증을 대상에서 실행
- [ ] Apple Silicon/8GB, Windows CPU/CUDA 실행 검증

## Phase 3 — Editor Integration Migration

- [x] 범용 Timeline Plan/Recipe/edit planner와 tests 이전
- [x] Premiere Preflight/Dry-run/approval common flow와 project cache 이전
- [x] 개인 콘텐츠 fixture 이름을 합성 일반명으로 변경
- [x] VESupport Recipe seconds v1에서 정렬된 action을 공통 정수 frame 계약으로 변환
- [ ] 미지원 Recipe action 전체 mapping과 프레임/timebase 호환 회귀 검증
- [ ] Schema-driven UXP UI 및 실제 host adapter 연결
- [ ] 실제 Premiere UXP 설치, persistent token, MOGRT, XML, Razor host 검증

## Phase 4–7 — Extensions, Workflow, Validation, Delivery

- [ ] Extension 등록/호환성 검사/sandbox 로더 구현
- [ ] Media Engine과 Premiere adapter 간 공통 Edit Plan 연결
- [ ] Windows/macOS 외장 Workspace 교차 재개 검증
- [x] 자동 회귀 테스트, public hygiene, 정책 검사와 hosted CI
- [ ] Windows Host Validation Checklist 실행
- [ ] Migration Report / patch notes와 후속 CI 상태 갱신
- [ ] 사용자 PR 검토 후 대상 저장소 정책으로 최종 병합

## 남은 완료 기준

이번 변경은 실제 엔진 및 편집 계획 코드의 마이그레이션을 포함하지만 **프로덕션 릴리스 준비 완료는 아닙니다**. Premiere/Windows, GPU, Apple Silicon, 외장 SSD 교차 검증과 Recipe frame adapter가 남았습니다.
