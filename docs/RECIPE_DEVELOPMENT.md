# Editing Recipe 개발 안내

Recipe는 반복 편집을 선언형 입력, 단계, 자산 참조, 트랙, 정수 프레임 위치 및 충돌 정책으로 표현합니다. 현재 Schema는 `insert_media`, `insert_audio`, `insert_mogrt`, `add_caption`, `split_clip`, `add_marker` Action 이름을 받지만, 해당 Action을 실제 실행하는 엔진은 없습니다.

## 실행 계약

```text
사용자 입력 → Schema/Extension 검사 → 자산 해석 → Edit Plan → Preflight → Preview → 승인 → 별도 시퀀스 실행 → 검증/결과
```

Recipe의 필수 안전 정책은 Preview, 승인, sequence clone, 원본 불변입니다. 누락 자산과 충돌은 기본적으로 실행을 막습니다. `condition`과 field mapping은 현재 데이터 영역일 뿐 실행 가능한 표현식/코드가 아닙니다.

합성 형식은 `contracts/examples/contracts-v1.json`의 `EditingRecipe` 항목에서 확인할 수 있습니다. Recipe compiler, dry-run과 host adapter는 미구현입니다.
