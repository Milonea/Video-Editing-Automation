# 보안 및 개인정보 정책

## 공개 저장소에 허용하지 않는 데이터

- 실제 원본 영상/오디오, Premiere·After Effects 프로젝트, 자막, 작업 보고서와 고객 자료
- 개인 콘텐츠 데이터베이스, 권리 확인 전의 이미지·음원·글꼴·MOGRT·템플릿
- 토큰, API Key, OAuth/Persistent Token, 계정 식별자와 사용자별 Persona
- 사용자명이 들어간 절대 경로, 장치 식별값, 로컬 캐시와 외장 Workspace manifest
- 원본 Git 저장소의 commit, branch, tag, release history

## 코드 라이선스와 로컬 자산

공개 프레임워크 코드에는 MIT License를 적용합니다. VEA 원본의 `LICENSE`는 MIT이며, 복사본의 패키지 metadata에 있던 상충 선언은 대상 사본에서 MIT로 맞췄습니다. automation_VESupport의 프로젝트 코드는 선생님의 명시적 선택으로 MIT 범위에 포함했습니다. Adobe SDK와 재배포 권리가 확인되지 않은 제3자 구성 요소는 복사하지 않았습니다.

사용자가 직접 제작·수정하는 외부 이미지, 음원, MOGRT와 콘텐츠 데이터베이스는 외장 SSD 또는 로컬 Workspace에서 계속 관리합니다. 이 자산은 공개 Git 이력에 올리지 않습니다. `.gitignore`가 대표 자산 확장자와 `assets/local/`, `extensions/local/`을 제외하며, 공개 변경 전 파일 경로와 라이선스를 별도 확인합니다. MIT 코드 라이선스는 별도 자산에 권리를 부여하지 않습니다.

## Extension과 파일 접근

향후 자산 resolver는 등록된 Workspace/Extension root 아래 상대경로만 허용하고 `..`, 절대경로, 심볼릭 링크 탈출을 검사해야 합니다. Extension 선언만으로 arbitrary code를 실행하지 않습니다. Premiere 파일 접근 토큰은 로컬 사용자 저장소에서 처리하며 JSON, 로그, PR에 기록하지 않습니다.

## 편집 안전과 복구

원본은 읽기 전용 입력으로 취급합니다. Preflight, fingerprint, 충돌 검사, preview, 승인, clone sequence, 사후 검증과 checkpoint를 실행 계약에 둡니다. 자동 삭제, 원본 덮어쓰기 또는 충돌 시 임의 교체는 기본 동작이 될 수 없습니다.

## 현재 검사 범위

이번 변경에는 실제 미디어 파일, 콘텐츠 자산, 사용자 project 또는 credential이 없습니다. 합성 JSON Fixture와 코드만 포함하며 공개 Hygiene 검사와 hosted CI에서 확인합니다.
