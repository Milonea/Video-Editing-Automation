# Windows Host Validation Checklist

**초기 상태:** `PENDING_HOST_VALIDATION` — 실제 제작 환경에서 체크하지 않았습니다.

- [ ] Windows에서 Python과 Node 설치·지원 버전 확인
- [ ] FFmpeg/FFprobe 경로와 버전 확인
- [ ] 외장 Workspace ID, 상대경로, Unicode 파일명 및 재연결 확인
- [ ] CPU backend 정상 실행 및 실패 진단 확인
- [ ] NVIDIA driver/CUDA/CTranslate2 capability를 실제 probe하고 fallback 확인
- [ ] Whisper 선택 설치, 모델 캐시, 중단 후 resume 및 설정 fingerprint 확인
- [ ] VFR 입력 분석, CFR 변환 map, 컷/자막 frame sync 확인
- [ ] 실제 Premiere Pro에서 UXP 패널 로드와 Capability 보고 확인
- [ ] Clone sequence 생성, 원본 sequence 보존, 잠긴 트랙 및 충돌 차단 확인
- [ ] 합성 또는 재배포 허가 자산만 사용해 승인 전 차단·승인 후 삽입을 확인
- [ ] 개인 제작 이미지·음원·MOGRT는 Workspace 밖으로 복사하지 않고 로컬에서만 확인
- [ ] JSX/CEP 호환을 지원 대상 버전별로 확인
- [ ] FCP7 XML import 후 audio stream, frame rate, caption sync 확인
- [ ] 장시간/대용량 처리의 CPU·GPU·RAM·disk peak 기록
- [ ] 프로세스 강제 중단 후 checkpoint로 재개하고 중복 실행/손상 없는지 확인
- [ ] 실패·부분 성공·완전 성공 상태와 보고서가 구분되는지 확인

실제 호스트 버전, 장치, 입력 합성/실제 여부, 로그·산출물의 위치, 각 항목의 PASS/FAIL 및 재현 단계를 기록합니다. 미실행 항목은 체크하지 않습니다.
