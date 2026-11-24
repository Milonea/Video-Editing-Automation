# Editing Recipe 개발 안내

공통 Recipe Schema는 반복 편집을 선언형 입력, 단계, 자산 참조, 트랙, 정수 프레임 위치 및 충돌 정책으로 표현합니다. VESupport에서 이전한 JavaScript planner는 검증된 Recipe를 Timeline Plan으로 컴파일하고 source-clone 기반 safe primitive로 실행할 수 있습니다. legacy planner v1은 초 단위입니다. `packages/javascript/editing-plans/legacy-contract-adapter.js`는 명시된 rational frame rate, project ID와 source fingerprint를 받아 공통 EditPlan으로 변환하며, 프레임에 정렬되지 않은 시간과 미지원 action을 거부합니다.

## 실행 계약

```text
사용자 입력 → Schema/Extension 검사 → 자산 해석 → Edit Plan → Preflight → Preview → 승인 → 별도 시퀀스 실행 → 검증/결과
```

Recipe의 필수 안전 정책은 Preview, 승인, sequence clone, 원본 불변입니다. 누락 자산과 충돌은 기본적으로 실행을 막습니다. `condition`과 field mapping은 현재 데이터 영역일 뿐 실행 가능한 표현식/코드가 아닙니다.

합성 공통 형식은 `contracts/examples/contracts-v1.json`의 `EditingRecipe` 항목, legacy planner fixture는 `packages/javascript/editing-plans/tests/fixtures/`에서 확인할 수 있습니다. 범용 fixture에는 실제 사용자 자산이 없습니다. Premiere API adapter, 전체 legacy action mapping과 Extension 로더는 미구현입니다.
