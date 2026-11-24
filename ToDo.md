# 개발 현황

이 문서는 다음 작업의 기준 목록입니다. `docs/FEATURE_SUPPORT_MATRIX.md`가 기능 상태의 기준이며, 이 파일은 실행 순서만 관리합니다.

## Phase 0 — Discovery

- [x] 두 원본과 공개 대상의 기본 브랜치 트리 및 기준 commit SHA 기록
- [x] 대상 템플릿과 브랜치·Pull Request 상태 조사
- [x] VEA 라이선스 파일과 패키지 메타데이터의 불일치 발견
- [x] 편집기 원본의 LICENSE 부재와 콘텐츠별 자산 확인
- [ ] 원본 코드의 재배포 권한과 최종 라이선스 기준 확정

## Phase 1 — Foundation

- [x] 공통 Schema v1과 합성 Fixture 정의
- [x] Python/JavaScript에서 같은 Fixture를 검사하는 테스트 추가
- [x] 프로젝트 프로필, 아키텍처, 보안 경계 및 현황 문서 작성
- [ ] JSON Schema 호환성 정책 및 역방향 호환성 테스트 정착

## Phase 2 — Media Engine Migration

- [ ] 권리 기준 해결 후 VEA 핵심 엔진·CLI·테스트 이전
- [ ] Workspace manifest를 사용자 중립 ID와 상대 경로 중심으로 이전
- [ ] Smart Silence Split과 전사 기능을 공통 계약에 연결
- [ ] CPU/CUDA Capability 자동 탐지 및 체크포인트 회귀 검증

## Phase 3 — Editor Integration Migration

- [ ] 편집기 자동화 코드의 공개·재배포 권한 확인
- [ ] Premiere 공통 작업 계약과 프로젝트별 캐시를 권리 승인된 코드로 이전 또는 재구현
- [ ] UXP 패널과 레거시 JSX 호환 경계를 확정
- [ ] 포맷·텍스트·이미지·오디오 삽입 기능을 범용 Asset/Recipe로 연결

## Phase 4–7 — Extensions, Workflow, Validation, Delivery

- [ ] 선언형 Extension 로더와 스키마 검증 구현
- [ ] Recipe 컴파일, Preflight, Dry-run, 승인 및 복구 구현
- [ ] Windows/macOS Workspace 교차 사용 테스트 추가
- [ ] Premiere UXP, JSX, MOGRT, XML 및 실제 타임라인 수동 검증
- [ ] 안정적인 CI aggregate check와 릴리스 게이트 설정
- [ ] 원본 프로젝트 이전 도구 및 사용자 마이그레이션 안내 제공

## 현재 차단 항목

1. VEA 저장소의 MIT LICENSE와 `pyproject.toml`의 `Proprietary` 선언 불일치
2. 편집기 자동화 저장소에 저장소 라이선스 파일이 없음
3. MOGRT, Adobe SDK 및 일부 외부 자산의 재배포 권한 미확인
4. 실제 Windows/Premiere 호스트가 없는 실행 환경에서 확인할 수 없는 통합 검증
