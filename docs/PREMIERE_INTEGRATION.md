# Premiere Integration 안내

## 통합 목표

Premiere adapter는 공통 Edit Plan과 Capability를 받아 Preflight를 수행하고, 충돌·잠금 트랙·누락 자산을 보고한 다음 편집 가능한 별도 시퀀스에서만 변경하도록 설계합니다. 실행 전 preview와 사용자 승인, 실행 후 결과 진단이 필수입니다.

기존 UXP와 레거시 JSX는 공통 데이터 검증 계층을 공유하되 호스트 API와 실제 지원 기능을 분리해 기록합니다. CEP와 After Effects 모듈은 지원 가치·라이선스·호스트 호환성을 확인하기 전까지 별도 어댑터 후보입니다.

## 현재 구현 상태

이번 대상 저장소에는 Premiere 패널이나 Adobe API 호출 코드가 없습니다. 두 원본의 편집기 소스 중 하나에는 라이선스 파일이 없고, 다른 원본에는 패키지 라이선스 선언 충돌이 있어 복사하지 않았습니다. UXP 설치, MOGRT 삽입, JSX, XML 가져오기, Persistent Token 복구와 실제 타임라인 변경은 `PENDING_HOST_VALIDATION`입니다.

## 향후 Capability 예시

`timeline.inspect`, `timeline.clone`, `timeline.insert_media`, `timeline.insert_mogrt`, `timeline.insert_audio`, `timeline.split_at_frame`, `project.import_xml`, `asset.persistent_access` 등 기능별로 지원 여부와 최소 호스트 버전을 명시합니다. 패널은 capability를 확인하지 않은 Action을 노출하지 않습니다.

설치 경로와 실제 검증 순서는 [Windows 호스트 체크리스트](WINDOWS_HOST_VALIDATION_CHECKLIST.md)에 기록합니다.
