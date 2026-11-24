# Premiere 공통 모듈

`error-sanitizer.js`, `host-operation-contract.js`, `project-item-cache.js`는 Premiere UXP 실행기에서 분리된 공통 안전 모듈입니다. 호스트 API는 인자로 주입하므로 Node.js에서 계약 검증을 수행할 수 있습니다.

`runInsertionFlow`는 외부 Workspace 선택, 자산 해석, Preflight, Dry-run, 승인된 삽입, 부분 성공 보고 순서를 강제합니다. Preflight가 명시적으로 통과하지 않거나 Dry-run이면 Premiere 삽입 함수를 호출하지 않습니다. 이 모듈만으로 UXP 설치 또는 Premiere 호스트 지원이 완료되는 것은 아닙니다.

개인 콘텐츠 설정, 사용자 자산, MOGRT 파일, Adobe SDK와 실제 편집기 UI는 이 공유 폴더에 포함하지 않습니다. 로컬 제작 이미지를 포함해 Workspace 외부 자산은 사용자 시스템에 보관합니다.
