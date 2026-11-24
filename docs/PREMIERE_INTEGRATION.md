# Premiere Integration 안내

## 통합 목표

Premiere adapter는 공통 Edit Plan과 Capability를 받아 Preflight를 수행하고, 충돌·잠금 트랙·누락 자산을 보고한 다음 편집 가능한 별도 시퀀스에서만 변경하도록 설계합니다. 실행 전 preview와 사용자 승인, 실행 후 결과 진단이 필수입니다.

기존 UXP와 레거시 JSX는 공통 데이터 검증 계층을 공유하되 호스트 API와 실제 지원 기능을 분리해 기록합니다. CEP와 After Effects 모듈은 지원 가치·라이선스·호스트 호환성을 확인하기 전까지 별도 어댑터 후보입니다.

## 현재 구현 상태

VEA Smart Silence 검토 UXP 패널, host-independent `runInsertionFlow`, 오류 경로 정리기와 프로젝트별 미디어 캐시가 이전되었습니다. VESupport의 고정 콘텐츠 버튼·DB·MOGRT 조작 UI는 콘텐츠 종속성이 있어 제외했습니다. 범용 Recipe planner는 이전했지만 초 단위 legacy plan과 공통 정수 프레임 Schema 연결 작업이 남아 있습니다.

UXP 패널의 정적 로직과 Premiere 공유 모듈은 Node.js 단위 테스트를 통과시킵니다. 실제 Premiere UXP 설치·Persistent Token·Razor 기반 분할·XML import·오디오/자막 싱크는 현재 대상 브랜치에서 다시 확인하지 않았으므로 `PENDING_HOST_VALIDATION`입니다. 원본 VEA 패널 문서에는 Premiere Beta 실험 기록이 있으나, 이를 이번 마이그레이션의 호스트 검증 완료로 계산하지 않습니다.

편집기 테스트에는 합성 미디어나 재배포 권한이 있는 자산만 사용합니다. 선생님의 외부 이미지·음원·MOGRT는 로컬 Workspace에 남기고 저장소에는 포함하지 않습니다.

## 향후 Capability 예시

`timeline.inspect`, `timeline.clone`, `timeline.insert_media`, `timeline.insert_mogrt`, `timeline.insert_audio`, `timeline.split_at_frame`, `project.import_xml`, `asset.persistent_access` 등 기능별로 지원 여부와 최소 호스트 버전을 명시합니다. 패널은 capability를 확인하지 않은 Action을 노출하지 않습니다.

설치 경로와 실제 검증 순서는 [Windows 호스트 체크리스트](WINDOWS_HOST_VALIDATION_CHECKLIST.md)에 기록합니다.
