# Project Profile

## Project

- Name: Video Editing Automation (VEA)
- Purpose: 범용 영상편집 자동화 프레임워크. 공개 구현에는 미디어 엔진, Smart Silence Split UXP 패널, Recipe/Edit Plan과 Premiere 공통 안전 모듈이 포함됩니다.
- Default branch: `main`
- Target platforms: macOS 개발, Windows 프로덕션 검증, 공통 Python/JavaScript 계약

## Personas and ownership

Persona 이름은 프레임워크에 포함하지 않습니다. 업무는 `workflow_manager`, `media_processing`, `editing_automation`, `quality_assurance`, `release_documentation` 역할로 구분하며 작업 배정은 GitHub PR과 `AgentTask`/`AgentResult` 계약에 기록합니다. 이 역할은 Git 권한이나 외부 서비스 권한을 늘리지 않습니다.

## Technology and commands

- Languages and formats: Python 3.11+, JavaScript/Node.js 20+, JSON Schema Draft 2020-12
- Setup: `python -m pip install -r requirements-dev.txt`; Node 테스트는 외부 패키지 설치 없이 실행
- Focused contract check: `python tools/validate_contracts.py`
- Python contract tests: `python -m unittest discover -s packages/python/tests -v`
- Migrated engine tests: `python -m pytest engine/tests -q`
- JavaScript tests: `npm test`
- Full required validation: 계약 검사, Python 계약/엔진 테스트, `npm test`, `python tools/check_docs.py`, `python tools/check_public_hygiene.py`, `python tools/check_policy_integrity.py`
- Post-merge smoke check: 같은 계약 검증 세트
- Hardware/host checks: Premiere Pro, UXP/JSX, CUDA, Apple Silicon 및 외장 Workspace는 실제 환경에서 별도 수동 확인

## Data and side-effect boundaries

- Sensitive data: 미디어, 고객 프로젝트, 사용자 Workspace manifest, 개인 확장팩, 로컬 경로, 계정 식별값, UXP Persistent Token, 인증 정보
- Never commit: 실제 영상/오디오, Premiere/After Effects 프로젝트, 로컬에서 제작·수정하는 이미지/음원/MOGRT, 사용자 데이터와 local config
- External services: GitHub는 사용자 승인된 PR 작업만. Multi Agent Industry, Notion 및 AI/클라우드 API는 선택적 adapter이며 현재 구현되지 않음
- Cost-generating actions: 현행 자동화 없음. 외부 유료 API는 별도 명시 승인 없이 추가 금지
- Destructive operations: 원본 미디어·기존 시퀀스의 덮어쓰기/삭제 금지. 공개 권리 미확인 파일은 push 전에 제외
- Recovery: 코드 변경은 revert 가능한 task branch/PR로 관리. 미디어 엔진 checkpoint는 이전되었으며 실제 중단·재개는 Windows와 Premiere 호스트에서 별도 검증

## Documentation and release

- Changelog: `CHANGELOG.md`
- Status source: `docs/FEATURE_SUPPORT_MATRIX.md`; 작업 순서 `ToDo.md`
- Manual release checks: Windows/Premiere host, GPU backend와 Workspace cross-host validation
- Code merge blocker: 개인정보·데이터 안전 문제, required CI 실패, 해결되지 않은 PR thread
- Release-only blocker: 실제 Premiere/Windows/대용량 media 검증 전에는 프로덕션 릴리스 금지

## License

공개 프레임워크의 프로젝트 코드에는 MIT License를 적용합니다. 개인 제작 자산과 재배포 권리가 별도로 확인되지 않은 제3자 자산은 이 라이선스 범위에 포함하지 않으며 저장소에 커밋하지 않습니다. 기존 `PROJECT_PROFILE.template.md`에서 이 프로젝트의 실제 값으로 채운 프로필입니다.
