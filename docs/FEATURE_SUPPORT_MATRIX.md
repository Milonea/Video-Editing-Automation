# 기능 지원표

이 표는 현재 공개 저장소에 존재하는 기능 상태의 단일 기준입니다. `계획`이나 `호스트 검증 대기`는 구현 완료를 의미하지 않습니다.

| 기능 | 현재 상태 | 검증 근거 / 남은 작업 |
| --- | --- | --- |
| Schema v1: Project/Asset/Stream/Timeline | 초기 구현 | JSON Schema와 합성 Fixture 검사; 실제 엔진 연결 없음 |
| Edit Plan / Recipe / Extension | Schema 구현 | 미리보기·승인·원본 보존 값 검증; 로더 및 실행기는 미구현 |
| Transcript / Subtitle | Schema 구현 | 프레임 범위 검증; 전사 파이프라인 미이전 |
| Execution / Diagnostic / Checkpoint / Validation Report | Schema 구현 | 구조 검사; 복구 가능한 실행기 미구현 |
| Agent task/result | Schema 구현 | 범용 역할 이름만 정의; 별도 Agent framework 연동 없음 |
| Python 계약 검사 | 구현 | JSON Schema Draft 2020-12와 안전 불변식 |
| JavaScript 계약 검사 | 구현 | 공통 fixture 검사와 경로·프레임·승인 안전 불변식 |
| 기존 `vea` CLI / FFmpeg / FFprobe | 차단 | 원본 라이선스 선언을 해결한 뒤 이전·회귀 테스트 필요 |
| Whisper CPU/CUDA/MLX | 미구현/검증 대기 | MLX는 원본에서도 실행 백엔드 미구현; 다른 백엔드는 이식되지 않음 |
| Smart Silence Split | 차단 | 계산/패널 이전과 Premiere 실제 시퀀스 검증 필요 |
| Premiere UXP 통합 패널 | 차단 | 권리 승인 및 실제 host 검증 필요 |
| 레거시 JSX / CEP / After Effects | 미확정 | 재배포 조건과 호스트 지원 버전 조사 필요 |
| macOS↔Windows Workspace | 계획 | manifest/resolver 마이그레이션 및 실제 외장 볼륨 테스트 필요 |
| 공개 배포 라이선스 | 미결정 | 원본 권리와 대상 프로젝트 라이선스 결정 전 |

CI 상태가 통과해도 실제 Premiere, 하드웨어, 외장 디스크 기능을 완료 처리하지 않습니다.
