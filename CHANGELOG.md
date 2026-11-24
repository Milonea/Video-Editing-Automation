# 변경 기록

이 문서는 공개 저장소에서 실제 구현·검증된 변경만 기록합니다. 아직 릴리스 태그는 만들지 않았습니다.

## Unreleased — 2026-11-24

- 기존 VEA Python 엔진, `vea` CLI, Workspace Resolver, config와 회귀 테스트를 clean-history 브랜치에 이전했습니다.
- Smart Silence 검토용 Premiere UXP 패널과 Node.js 순수 로직 테스트를 이전했습니다.
- automation_VESupport의 Timeline Plan, Recipe, 이미지·자막·무음 planner, 안전 편집 primitive와 legacy fixture를 범용화해 이전했습니다.
- 초 단위 legacy edit plan을 정수 프레임 기반 공통 EditPlan으로 바꾸는 명시적 adapter를 추가했습니다. 프레임 정렬 오류와 미지원 action은 추측하거나 반올림하지 않고 차단합니다.
- Premiere 실행 공통 계약에 Preflight, Dry-run, 명시적 approval gate, error sanitization과 project cache 모듈을 추가했습니다.
- common/OS/profile/local/project/explicit/task 설정 병합, development/lightweight/production/validation 프로필 및 CLI `--profile`을 추가했습니다.
- macOS/Windows 설치 스크립트를 경량 기본 설치로 바꾸고 Whisper CPU/CUDA 의존성을 명시적으로 선택하게 했습니다.
- 개인 Persona 필드와 사용자 Workspace 식별자를 범용화하고 개인 제작 이미지·음원·MOGRT·콘텐츠 DB·Adobe SDK는 공개 저장소에서 제외했습니다.
- 대상 템플릿 정책을 유지하고 한국어 마이그레이션·보안·플랫폼·호스트 검증 문서를 갱신했습니다.
