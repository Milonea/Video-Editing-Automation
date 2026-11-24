# 외부 Workspace 안내

## 목표 데이터 경계

소스 저장소와 개발 환경은 각 컴퓨터의 내장 SSD에 둡니다. 외장 SSD 또는 사용자 지정 Workspace에는 영상 원본, Premiere 프로젝트, 전사·자막, 타임라인 계획, 편집 산출물, 개인 Extension, 사용자가 직접 제작·수정하는 이미지·음원·MOGRT 및 체크포인트를 저장합니다. 이 개인 자산은 Git에 커밋하지 않습니다.

## 식별 및 경로 규칙

- Workspace는 사람이나 장치 이름이 아닌 사용자가 생성한 안정적인 Workspace ID로 구분합니다.
- 프로젝트 내부 참조는 상대경로와 asset ID를 우선합니다.
- 절대경로는 해당 컴퓨터의 로컬 resolver 안에서만 사용합니다.
- 연결되지 않은 Workspace를 다른 경로로 자동 대체하지 않습니다.
- 일치 ID가 여러 볼륨에서 발견되면 선택을 보류하고 진단 정보를 냅니다.
- 재연결 시 기존 ID와 manifest를 검증하고, 저장 중단 후 임시 파일을 먼저 검사합니다.

## 현재 구현 상태

VEA의 Workspace Resolver와 안전한 상대경로 검사, 비덮어쓰기 manifest 생성, CLI dry-run 및 설정 우선순위가 이전되었습니다. manifest 기본 파일명은 `.vea-workspace.json`입니다. 기존 로컬 manifest는 원본을 보존한 채 새 이름으로 복사하고 Workspace ID와 프로젝트 상대경로를 확인한 다음 `vea workspace resolve`로 재검증하세요. 실제 외장 SSD의 양방향 macOS/Windows 전환 검증은 아직 수행하지 않았습니다.

macOS와 Windows에서 동시 쓰기를 하지 말고, 프로젝트 저장을 마친 뒤 안전하게 분리합니다. 실제 경로 재연결은 양쪽 OS에서 검증되기 전까지 지원 완료로 보지 않습니다.
