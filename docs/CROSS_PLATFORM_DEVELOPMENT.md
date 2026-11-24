# 크로스플랫폼 개발 안내

## 정책

- macOS는 기본 개발, 코드 리뷰, 공통 테스트와 경량 전처리를 고려한 환경입니다.
- Windows는 실제 영상 제작, Premiere 자동화, CUDA/CPU 처리 및 데이터 복구를 우선 검증할 환경입니다.
- 두 운영체제는 동일한 Schema, Workspace ID와 프로젝트 상대경로를 사용해야 합니다.
- 어떤 OS 조합도 실제 검증 전에는 호환 완료로 표시하지 않습니다.

## 설정 우선순위

엔진 설정 로더는 낮은 우선순위부터 다음 순서로 병합합니다.

1. 공통 기본값
2. OS별 설정
3. 실행 프로필 (`development`, `lightweight`, `production`, `validation`)
4. 사용자 로컬 설정
5. 프로젝트 설정
6. 명시적 설정 파일
7. CLI 실행 옵션

더 높은 항목이 같은 키의 낮은 값을 덮습니다. CLI에서는 각 명령 뒤에 `--profile development|lightweight|production|validation`을 지정할 수 있고 `VEA_PROFILE` 환경변수도 지원합니다. 네 가지 프로필은 실제 설치된 모델이나 backend를 보장하지 않으며 Whisper/GPU 의존성을 기본 설치하지 않습니다. JavaScript/UXP 설정도 같은 계약을 따라야 합니다.

## 공통 실행 계약

타임라인 위치는 정수 프레임, 프레임레이트는 분자/분모로 전달합니다. OS 경로는 Workspace Resolver가 실제 mount 위치로 변환하고, 공통 JSON에는 절대경로를 저장하지 않습니다. backend 자동 선택은 실행 시 capability probe를 통과한 결과만 사용합니다.

## 개발과 영상 자료의 분리

Git clone, virtualenv, Node 의존성과 build 결과는 각 컴퓨터의 내장 SSD에 둡니다. 외장 Workspace에는 원본 영상, 편집 프로젝트, 전사·자막·계획·체크포인트와 산출물을 둡니다. 외장 저장장치에는 한 번에 하나의 호스트만 쓰기 작업을 수행합니다.

현재 구현 상태는 [기능 지원표](FEATURE_SUPPORT_MATRIX.md)를, 실제 교차 운영 단계는 [외부 Workspace 안내](EXTERNAL_WORKSPACE.md)를 확인하세요.
