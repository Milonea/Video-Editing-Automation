# 기능 지원표

이 표는 대상 브랜치에 실제 포함된 기능과 검증 상태의 기준입니다. 자동 테스트 통과, CI 통과, 실제 호스트 검증을 서로 구분합니다.

| 기능 | 현재 상태 | 검증 근거 / 남은 작업 |
| --- | --- | --- |
| 공통 contracts v1: Project/Asset/Stream/Timeline/Edit Plan/Recipe/Transcript/Extension/Agent | 구현 | JSON Schema, 합성 Fixture, Python/JavaScript 검사 |
| Python 계약 검사 및 JavaScript 계약 검사 | 구현 | 공통 Fixture 검증 및 안전 불변식 단위 테스트 |
| 기존 vea CLI | 코드 이전 | 명령 호환성을 유지; 엔진 pytest 회귀 테스트 실행 필요 |
| VEA FFprobe/FFmpeg 미디어 분석, 다중 오디오, 전처리와 FCP7 XML | 코드 이전 | source test 이전; 실제 코덱·대용량 미디어 테스트 별도 |
| 타임코드, CFR/VFR mapping, 자막, Glossary, checkpoint, version/report | 코드 이전 | 엔진 단위 회귀 테스트; 실제 파일과 cross-OS 검사 별도 |
| Whisper CPU/CUDA | 코드 이전, host 검증 대기 | optional dependencies와 capability 검사; 실제 CPU/CUDA 런타임 미검증 |
| Whisper MLX | 미구현 | 원본에서도 backend 실행 경로가 확인되지 않음 |
| Smart Silence Split 계산 | 코드 이전 | Python 테스트와 합성 fixture; 실제 Premiere 결과는 별도 확인 |
| Smart Silence Premiere UXP 검토 패널 | 코드 이전, host 검증 대기 | 순수 JS 테스트; 설치·토큰·시퀀스 동작 미재검증 |
| Premiere Preflight / Dry-run / explicit approval | 공통 안전 모듈 구현 | Mock 테스트; 실제 UXP Adapter 미연결 |
| 프로젝트별 Media Import Cache, error sanitization | 공통 모듈 이전 | Node.js 단위 테스트; Premiere 성능 검증 대기 |
| Timeline Plan / Recipe planner | legacy planner 이전 + 부분 frame adapter | 원본 Node 테스트; 명시 FPS에서 프레임 정렬된 subset을 공통 EditPlan으로 변환, 비정렬 시간·미지원 action은 차단 |
| 이미지/영상/MOGRT/오디오 편집 계획 | planner에 포함 | Asset 참조와 충돌 검사; 실제 Premiere 삽입은 host 미검증 |
| Extension manifest 및 capability | Schema 구현 | 등록·호환성 검사·sandbox loader는 미구현 |
| 고유 콘텐츠 UI/DB 및 personal extension | 공개 코어에서 제외 | 사용자는 로컬 Workspace에서 별도 유지; 공개 자산 미포함 |
| JSX/CEP/After Effects | 미이전 | Adobe SDK 및 호스트별 권리/호환성 확인 후 결정 |
| macOS↔Windows Workspace 교차 편집 | 코드 이전, 실제 검증 대기 | resolver/config/profile 구현; 외장 SSD 양방향 실측 미완료 |
| development/lightweight/production/validation 설정 profile | 구현 | config merge unit test; OS별 실제 성능값은 검증 대기 |
| MIT License | 설정 완료 | root LICENSE와 Python package metadata 일치; 로컬/제3자 자산은 범위 밖 |
| Windows/Premiere/GPU/Apple Silicon 릴리스 준비 | Pending host validation | 이 실행 환경에서 실기기 검증 수행하지 않음 |

`PENDING_HOST_VALIDATION`는 자동화 검증만으로 완료 처리하지 않는 호스트·하드웨어 검증 상태입니다.
