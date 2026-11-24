# 검증 보고서

**검증 기준일:** 2026-11-24 (KST)  
**검증 환경:** Linux 컨테이너, Python 3.12, Node.js 24.22.3  
**범위:** 마이그레이션 코드·설정·Schema·합성 Fixture

## 자동 검증 결과

| 검사 | 결과 |
| --- | --- |
| Python JSON Schema / 공통 Fixture | PASS — 27개 contract definition |
| Python contract 단위 테스트 | PASS — 7 tests |
| 이전된 VEA 엔진 회귀 테스트 | PASS — 113 tests |
| JavaScript / Recipe / UXP / Premiere 공통 모듈 | PASS — 54 tests |
| Python compileall | PASS |
| Node.js 구문 검사 | PASS — 28 JavaScript files |
| 엔진 editable package build/install, optional backend 제외 | PASS |
| 문서 내부 링크 | PASS |
| Secret·개인 경로·금지 미디어 파일 Hygiene | PASS — 147 files scanned |
| 대상 저장소 정책 무결성 검사 | PASS |
| GitHub hosted CI | 현재 PR의 새 migration commit을 push한 뒤 확인 예정 |

기본 개발 의존성에 pytest만 추가했으며 Whisper 모델·CUDA runtime·Adobe SDK는 설치하지 않았습니다. Node 테스트 중 npm 환경이 http-proxy 설정 경고를 출력했지만 검사 결과는 PASS였습니다.

## 공개 자료 검사 범위

최종 변경 파일에는 실제 영상·음원, 이미지 자산, MOGRT, Premiere/After Effects 프로젝트, 외부 DB, 계정 credential, UXP Persistent Token이 없습니다. 개인 로컬 이미지·음원·MOGRT와 사용자 Extension 디렉터리는 .gitignore에 추가했습니다. VESupport의 Adobe CSInterface SDK와 콘텐츠별 고정 패널/DB/패치 코드는 이식하지 않았습니다.

## PENDING_HOST_VALIDATION

아래 검증은 위 자동 검사로 대체하지 않습니다.

- Apple Silicon M2/8GB에서 가벼운 작업과 메모리 사용량
- Windows CPU/CUDA 전사, 대용량 영상 처리와 체크포인트 재개
- 실제 Premiere UXP 패널 설치, Persistent Token 복구, timeline split 동작
- MOGRT 삽입, XML 가져오기, 실제 오디오/자막 sync
- 외장 SSD Workspace의 macOS→Windows 및 Windows→macOS 재연결
- 실제 Premiere 프로젝트 복구와 원본/기존 sequence 무결성

검증하지 않은 Premiere·운영체제·GPU 기능은 완료 또는 프로덕션 지원으로 표시하지 않습니다.
