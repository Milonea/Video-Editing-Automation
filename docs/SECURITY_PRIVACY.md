# 보안 및 개인정보 정책

## 공개 저장소에 허용하지 않는 데이터

- 실제 원본 영상/오디오, Premiere·After Effects 프로젝트, 자막, 작업 보고서와 고객 자료
- 개인 콘텐츠 데이터베이스, 권리 확인 전의 이미지·음원·글꼴·MOGRT·템플릿
- 토큰, API Key, OAuth/Persistent Token, 계정 식별자와 사용자별 Persona
- 사용자명이 들어간 절대 경로, 장치 식별값, 로컬 캐시와 외장 Workspace manifest
- 원본 Git 저장소의 commit, branch, tag, release history

## 코드 공개와 권리 조건

현재 조사에서 원본 엔진의 LICENSE와 package metadata가 상충하고, 편집기 자동화 저장소에는 LICENSE가 없는 것을 확인했습니다. 권리 조건이 해결될 때까지 해당 코드는 공개 변경에서 분리합니다. 이 공개 대상 저장소의 최종 라이선스도 임의로 정하지 않습니다.

## Extension과 파일 접근

향후 자산 resolver는 등록된 Workspace/Extension root 아래 상대경로만 허용하고 `..`, 절대경로, 심볼릭 링크 탈출을 검사해야 합니다. Extension 선언만으로 arbitrary code를 실행하지 않습니다. Premiere 파일 접근 토큰은 로컬 사용자 저장소에서 처리하며 JSON, 로그, PR에 기록하지 않습니다.

## 편집 안전과 복구

원본은 읽기 전용 입력으로 취급합니다. Preflight, fingerprint, 충돌 검사, preview, 승인, clone sequence, 사후 검증과 checkpoint를 실행 계약에 둡니다. 자동 삭제, 원본 덮어쓰기 또는 충돌 시 임의 교체는 기본 동작이 될 수 없습니다.

## 현재 검사 범위

이번 코드에는 합성 JSON Fixture 외 미디어 파일이 없고 외부 서비스 credential을 사용하지 않습니다. Pull Request에 포함되는 모든 경로에 Secret, 개인 경로, 비허용 미디어 확장자 검사를 실행하며 결과를 검증 보고서와 hosted CI에서 확인합니다.
