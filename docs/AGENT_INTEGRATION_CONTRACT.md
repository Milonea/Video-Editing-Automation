# Agent Integration Contract

공개 프레임워크는 특정 Persona를 포함하거나 필수 Agent runtime에 의존하지 않습니다. 이 저장소의 `AgentTask`와 `AgentResult`는 에이전트, 사람 작업자 또는 선택적 Multi Agent Industry adapter 사이에서 교환하는 최소 데이터 계약입니다.

## 역할 식별자

- `workflow_manager`
- `media_processing`
- `editing_automation`
- `quality_assurance`
- `release_documentation`

역할 ID는 업무 책임만 표현합니다. 이름, 캐릭터, 말투, 계정, 프로젝트 메모리와 사용자 선호는 사용자가 선택한 외부 설정으로 관리합니다.

## 전달 규칙

요청에는 `task_id`, `project_id`, 역할, 목표, 구조화된 입력, 제약, 수락 기준과 생성 시각이 포함됩니다. 결과에는 같은 `task_id`, `completed/partial/blocked/failed` 상태, 요약, 상대 artifact 참조, 진단과 완료 시각이 포함됩니다. 실제 미디어는 요청 본문에 포함하지 않고 Workspace 경로 또는 별도 사용자 권한으로 참조합니다.

Multi Agent Industry 연동은 선택적 Adapter로 구현해야 하며, 이 프로젝트는 독립 실행을 유지합니다. 이번 저장소에는 네트워크 연결이나 외부 서비스 인증 기능이 없습니다.
