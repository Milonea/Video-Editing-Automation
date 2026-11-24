# Video Editing Automation (VEA)

Video Editing Automation은 영상 분석, 편집 계획, 편집기 연동을 공통 데이터 계약으로 연결하는 범용 영상편집 자동화 프레임워크입니다. 원본 미디어와 기존 편집 프로젝트를 보존하고, 실행 전 계획 확인과 승인, 실행 후 검증을 기본으로 둡니다.

## 현재 상태

현재 저장소에는 언어 독립적인 계약 Schema, 합성 예제, Python 검증기, JavaScript 안전 검사와 자동 테스트가 들어 있습니다. 기존 영상 엔진과 Premiere 구현은 아직 이 저장소로 이전되지 않았습니다. 원본 저장소의 라이선스 표기가 서로 맞지 않거나 명시되지 않아, 권리 기준을 확인할 때까지 해당 소스와 자산은 공개 브랜치에서 제외했습니다. 따라서 현재 상태는 **기반 구현 단계**이며 실제 제작용 릴리스로 사용할 수 없습니다.

| 영역 | 상태 |
| --- | --- |
| 공유 계약과 합성 Fixture | 구현 및 자동 검증 완료 |
| Python / JavaScript 계약 안전 검사 | 초기 구현 및 테스트 완료 |
| 미디어 엔진 및 기존 `vea` CLI | 이전 차단: 라이선스 기준 확인 필요 |
| Premiere 패널 및 편집기 어댑터 | 이전 차단: 라이선스 기준 확인 필요 |
| Windows 실사용 / Premiere 호스트 | 검증 대기 |
| 배포 라이선스 | 미결정 |

상세 현황은 [기능 지원표](docs/FEATURE_SUPPORT_MATRIX.md), [Migration Matrix](docs/MIGRATION_MATRIX.md), [검증 보고서](docs/VALIDATION_REPORT.md)를 기준으로 확인하세요.

## 개발 및 제작 정책

- macOS를 주 개발 환경으로 고려하고, 저사양 환경의 기본 검증은 가볍게 유지합니다.
- Windows를 실제 영상 제작과 Premiere 검증의 우선 환경으로 둡니다.
- 공통 실행 계약은 운영체제, 하드웨어, GPU 백엔드와 편집기 API를 분리합니다.
- 타임라인 위치는 부동소수 초 대신 정수 프레임과 유리수 프레임레이트로 표현합니다.
- 모든 편집 Recipe는 미리보기, 명시적 승인, 원본 보존을 요구합니다.
- 영상 원본, 프로젝트 파일, 개인 확장팩, 토큰, MOGRT 및 실제 제작 자산은 저장소에 넣지 않습니다.

## 계약 검사 실행

Python 3.11 이상과 Node.js 20 이상이 필요합니다. 런타임 검증용 Python 의존성은 선택 설치이며 미디어 처리 모델이나 GPU 런타임은 포함하지 않습니다.

```bash
python -m pip install -r requirements-dev.txt
python tools/validate_contracts.py
python -m unittest discover -s packages/python/tests -v
npm test
```

Schema 기준은 [`contracts/schemas/contracts-v1.schema.json`](contracts/schemas/contracts-v1.schema.json)이며, Python과 JavaScript 테스트는 [`contracts/examples/contracts-v1.json`](contracts/examples/contracts-v1.json)의 같은 합성 Fixture를 읽습니다.

## 다음 단계

1. 원본 코드의 상충하는 라이선스 표기를 해결합니다.
2. 허가된 범위에서 미디어 엔진과 Premiere 공통 모듈을 이전합니다.
3. 계약에 연결된 Edit Plan, Preflight, 체크포인트와 Recipe 실행기를 구현합니다.
4. Windows 및 Premiere 실제 호스트 검증을 별도로 수행합니다.

개발 정책과 진행 순서는 [CONCEPT.md](CONCEPT.md), [기여 안내](CONTRIBUTING.md), [ToDo.md](ToDo.md)를 참고하세요. 저장소의 최종 배포 라이선스는 아직 결정되지 않았습니다.
