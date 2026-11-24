# 프로젝트 개념

## 목적

Video Editing Automation(VEA)은 다양한 영상 제작자가 자기 콘텐츠와 작업 환경에 맞는 자동화 확장을 붙일 수 있도록, 미디어 처리 엔진과 영상 편집기 통합을 느슨하게 연결하는 프레임워크입니다. 저장소는 범용 실행 계약과 안전한 기본 동작을 제공하고, 사용자 데이터·개인 페르소나·콘텐츠별 자산은 별도 Workspace와 Extension에 둡니다.

현재 구현에는 공통 계약, VEA Python 엔진, Smart Silence 검토용 UXP 패널, 범용 JavaScript 편집 계획기와 Premiere 실행 안전 모듈이 포함됩니다. Recipe의 시간 표현을 공통 정수 프레임 계약으로 연결하고 실제 Premiere/Windows 환경에서 검증하는 작업은 남아 있습니다.

## 공식 운영 원칙

1. **원본 보존:** 원본 파일과 기존 편집 시퀀스를 직접 덮어쓰거나 삭제하는 작업을 금지합니다.
2. **계획과 실행의 동일성:** Dry-run과 실제 실행은 같은 Edit Plan 계산 결과를 사용합니다.
3. **승인 우선:** 실행 전에 Preflight와 충돌 미리보기를 제공하고, 편집기 변경은 사용자 승인을 요구합니다.
4. **재개 가능성:** 체크포인트, 입력 지문, 명확한 부분 성공 상태를 보존합니다.
5. **상대 경로:** Workspace ID와 상대 경로를 우선하고, OS별 경로 차이는 resolver에 한정합니다.
6. **능력 확인:** GPU나 편집기가 설치되어 있다는 사실만으로 기능 지원을 주장하지 않습니다.
7. **확장 격리:** 콘텐츠별 데이터와 기능은 선언형 Extension 및 Recipe로 제공하며, 임의 코드 실행은 자동 허용하지 않습니다.
8. **검증 상태 분리:** Schema 검사, 단위 테스트, CI, 실제 Windows·Premiere 호스트 검증을 서로 다른 상태로 기록합니다.

## 플랫폼 정책

- **macOS-first Development:** 소스 작성, 리뷰, 가벼운 분석, 정적 검사와 공통 테스트를 고려합니다.
- **Windows-first Production:** 실제 미디어 처리, GPU 전사, Premiere 자동화와 데이터 복구의 우선 검증 환경입니다.
- **Cross-platform Runtime:** 두 운영체제는 동일한 Schema와 프로젝트 계약을 공유합니다. 다른 조합도 설계상 허용하되, 검증되지 않은 호스트 호환성은 보장하지 않습니다.

참고용 개발·프로덕션 하드웨어는 필수 요구사항이 아닙니다. 실행 프로필은 사용 가능한 메모리, CPU, GPU 및 호스트 Capability를 검사해 선택해야 합니다.

## 모듈 경계

| 모듈 | 책임 | 현재 상태 |
| --- | --- | --- |
| Shared Contracts | Project, Media, Timeline, Plan, Recipe, Extension 및 결과 Schema | Schema 및 Python/JavaScript 검사 구현 |
| Media Engine | 미디어 분석, 전사, 러프컷, 자막, 체크포인트 | VEA 코드 이전 및 단위 회귀 테스트; 실제 OS/backend 검증 대기 |
| Editor Integration | Premiere UXP/JSX, Preflight, 삽입 및 결과 확인 | Smart Silence UXP와 host-independent 안전 모듈 이전; 실제 Premiere 통합 대기 |
| Extension / Recipe | 선언형 데이터·기능 등록과 승인 실행 | 기존 Recipe planner 이전; 프레임 정렬 action adapter 구현; Extension 로더 미구현 |
| Agent Adapter | 역할 기반 작업 요청·결과 계약 | 선택적 역할·요청·결과 계약 정의 |

## 라이선스와 공개 경계

공개 프로젝트 코드는 MIT License로 배포합니다. 원본 VEA에 이미 포함된 MIT LICENSE와 상충하던 패키지 metadata는 대상 사본에서 MIT로 정리했습니다. automation_VESupport 코드는 선생님의 명시적 선택에 따라 MIT로 이식합니다. Adobe SDK와 권리 확인이 필요한 이미지·음원·MOGRT·콘텐츠 데이터는 가져오지 않았으며, 직접 제작·수정하는 자산은 로컬 Workspace에만 둡니다.
