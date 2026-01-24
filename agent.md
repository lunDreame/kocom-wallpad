# AI Agent Context: Enterprise-Master Kocom Wallpad Integration

## 🎯 Project Mission
Elfin-EW11 브릿지를 통한 코콤 월패드 통합 시스템의 '제품화'를 달성한다. 고지연(700ms+) 환경에서도 무결점 작동을 보장하며, 최신 소프트웨어 아키텍처와 상세한 한국어 문서화를 통해 유지보수성을 극대화한다.

## 🧠 Enterprise Architecture & Quality
1. **Defensive Programming:** 모든 외부 입력 패킷은 잠재적 오염을 가정하고 엄격히 검증한다. 논리적 범위를 벗어난 값은 Sanity Check를 통해 차단한다.
2. **Concurrency & Lock:** RS485 반이중(Half-duplex) 통신 특성을 고려하여 `asyncio.Lock()` 기반의 전송 제어와 패킷 간 유휴 시간(200ms)을 보장한다.
3. **Self-Healing Strategy:** 연속된 체크섬 오류나 소켓 타임아웃 발생 시, 지수 백오프 재연결 및 버퍼 초기화 시퀀스를 실행한다.
4. **Diagnostic Observability:** 가동 시간, 에러율, 신호 강도 등을 HA 진단 센서로 노출하여 운영 가시성을 확보한다.

## 🛠 Technical Standards
- **Platform:** Home Assistant Core 2025.12+ (Python 3.13 최적화)
- **Library:** `pyserial-asyncio-fast`를 기반으로 한 비동기 논블로킹 I/O 필수.
- **2026.7 Compliance:** 모든 기기 식별자는 최신 튜플 형식을 사용하며, YAML 설정을 배제한 UI 기반 Config Flow 표준을 준수한다.
- **CI/CD:** `ruff`, `mypy`, `hassfest`를 통한 자동 코드 품질 관리를 수행한다.

## 📖 Localization & Documentation
1. **Language:** 모든 주석, Docstring, 커밋 메시지는 **한국어(UTF-8)**로 상세하게 작성한다.
2. **Docstring Style:** Google Python Style Guide를 준수하며, 한국어로 의도와 예외 상황을 상세히 기술한다.
3. **Commit Format:** `[유형] 상세 내용` (예: `[개선] 순환 버퍼 도입 및 한글 주석 상세화`)
4. **README Quality:** Mermaid 다이어그램을 포함한 시각적 문서화와 상세한 트러블슈팅 가이드를 제공한다.

## 🧪 Testing Requirements
- `unittest.mock`을 활용하여 실제 장비 없이도 통신 프로토콜을 검증할 수 있는 단위 테스트 코드를 작성 및 유지한다.
