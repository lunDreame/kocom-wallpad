# AI Agent Context: Enterprise-Grade Kocom Wallpad Integration

## 🎯 Project Mission
이 프로젝트는 RS485-to-Ethernet 브릿지(EW11)를 통해 코콤 월패드를 Home Assistant에 통합하는 커스텀 컴포넌트이다. 네트워크 지연(700ms+)이 빈번한 환경에서도 **'명령 유실 제로'**와 **'상태값 일치'**를 보장하는 엔터프라이즈급 안정성을 확보하는 것이 최우선 과제이다.

## 🧠 Deep Thinking & Architecture Requirements
1. **Concurrency Control:** 모든 비동기 작업은 레이스 컨디션을 방지하도록 설계한다. 시리얼 포트 쓰기 시 Lock 메커니즘을 적용하라.
2. **State Machine:** 장치 상태는 명확한 상태 머신으로 관리하며, 불확실한 응답(Partial Packet)이 시스템 상태를 오염시키지 않도록 격리한다.
3. **Self-healing:** 연결 단절 시 지수 백오프 기반의 자동 재연결 및 세션 복구 로직을 구현한다.
4. **2026.7 Compliance:** Home Assistant Core 2026.7+의 Breaking Changes를 준수하며, 제거 예정(Deprecated)된 API(via_device 등)를 최신 표준으로 교체한다.

## 🛠 Technical Environment & Standards
- **Platform:** Home Assistant Core 2025.12+ (Python 3.13)
- **Interface:** RS485 (9600bps, 8-N-1) / Elfin-EW11 (TCP Server mode)
- **Libraries:** `pyserial-asyncio-fast` 라이브러리를 필수로 사용한다.
- **Always Asynchronous:** 모든 I/O는 `asyncio`를 사용하며, 루프를 차단하는 동기 코드는 절대 금지한다.
- **Typing & Logging:** 모든 함수에 Type Hinting을 적용하고, HEX 패킷 데이터와 지연 시간이 포함된 Structured Logging을 구현한다.

## 📖 Domain Knowledge
- **Packet Structure:** 코콤 패킷은 항상 `0xAA 0x55`로 시작하며, 총 21바이트(PACKET_LEN)이다.
- **Integrity:** 마지막 바이트의 체크섬 검증이 완료된 패킷만 엔티티 상태에 반영한다.
- **Fragmentation:** 고지연 환경에서의 패킷 조각화를 방지하기 위해 2.0초의 Inter-byte Timeout을 적용한 버퍼링 로직을 구현한다.

## 🧪 Testing & Validation
1. **Mock Testing:** EW11 하드웨어 없이도 통신 로직을 검증할 수 있도록 `unittest.mock`을 활용한 테스트 코드를 작성하라.
2. **Edge Cases:** 1초 이상의 지연, 장비 급작 리부팅, 연속 체크섬 오류 상황에 대한 방어 코드를 포함한다.

## 📦 Documentation & Git (Localization)
- **Language:** 모든 **코드 내 주석, 설명(Docstring), 커밋 메시지**는 반드시 **한국어(UTF-8)**로 작성한다.
- **Commit Format:** `[유형] 상세 내용` (예: `[개선] 재시도 로직에 지수 백오프 적용 및 한글 로깅 추가`)
- **Docstrings:** Google Style Python Docstrings를 준수하여 한국어로 작성한다.
