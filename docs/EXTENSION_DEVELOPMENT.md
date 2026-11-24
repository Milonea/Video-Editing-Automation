# Extension 개발 안내

Extension은 콘텐츠별 Schema, Asset root, Glossary, Recipe와 Action 이름을 코어 밖에서 선언합니다. 현재 `contracts-v1.schema.json`에는 `ExtensionManifest`와 `CapabilityDeclaration` 형식이 정의되어 있습니다.

## 안전 규칙

- asset root와 참조 파일은 등록된 Extension root 안의 상대경로로 지정합니다.
- Schema validation과 capability 확인이 끝나기 전에는 Extension을 로드하지 않습니다.
- 임의 JavaScript/JSX 실행을 Manifest만으로 허용하지 않습니다.
- 필수 Capability가 없는 호스트에서는 Action을 비활성화합니다.
- 사용자 승인과 Preview가 필요한 편집 동작을 Extension 정책에서 끌 수 없습니다.
- 민감한 토큰, 실제 계정 ID와 개인 프로젝트 데이터는 Extension 패키지에 넣지 않습니다.

## 현재 한계

Manifest Schema와 합성 예제만 있습니다. Extension 발견·등록·호환성 범위 검사·사용자 승인 UI·자산 루트 sandbox는 미구현입니다. 실제 콘텐츠 확장팩은 공개 저장소로 이전하지 않았습니다.
