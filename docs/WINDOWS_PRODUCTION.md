# Windows 프로덕션 안내

Windows는 실제 미디어 제작과 Premiere Pro 검증의 우선 대상입니다. Ryzen 9 3900X, RTX 2070 SUPER, RAM 64GB는 성능 참고 사양이며 필수 요구사항이 아닙니다.

## 현재 상태

이번 저장소에는 프로덕션 미디어 엔진, 기존 CLI, UXP 패널 및 설치 스크립트가 없습니다. 사용자는 이 문서만으로 실제 프로젝트를 자동 처리할 수 없습니다. 라이선스 확인 후 엔진을 이전하고 실제 Windows 호스트에서 검증해야 합니다.

## 릴리스 전에 필요한 검증

- Python·FFmpeg·FFprobe 설치와 버전 보고
- CPU 및 CUDA capability 탐지, 탐지 실패 시 안전한 fallback
- 선택 의존성만 설치하고 모델 캐시 위치 확인
- 원본 영상 보존 및 임시 디스크 공간 계산
- 다중 오디오 스트림과 자막·타임코드 싱크
- 대용량 미디어 처리 중 메모리·디스크 사용량
- 중단 후 체크포인트에서 재개 및 결과물 검증
- Premiere clone sequence, 충돌, 승인, 실행 결과 기록
- 외장 Workspace 연결 해제·재연결과 Unicode 경로

성능 테스트가 성공해도 원본 프로젝트 무결성이나 Premiere 결과를 자동으로 보증하지 않습니다. 체크리스트는 [Windows 호스트 검증표](WINDOWS_HOST_VALIDATION_CHECKLIST.md)를 사용합니다.
