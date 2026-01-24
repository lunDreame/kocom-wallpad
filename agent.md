# AI Agent Context for Kocom Wallpad Integration

## Project Mission
이 프로젝트는 RS485-to-Ethernet 브릿지(EW11)를 통해 코콤 월패드를 Home Assistant에 통합하는 커스텀 컴포넌트이다. 네트워크 지연이 빈번한 환경에서도 **'명령 유실 제로'**와 **'상태값 일치'**를 보장하는 것이 최우선 과제이다.

## Technical Environment
- **Platform:** Home Assistant Core 2025.12+ (Python 3.13)
- **Interface:** RS485 (9600bps, 8-N-1)
- **Bridge:** Elfin-EW11 (TCP Server mode)
- **Expected Latency:** Periodic spikes up to 700ms

## Coding Standards
1. **Always Asynchronous:** 모든 I/O는 `asyncio`를 사용하며, 루프를 차단하는 동기 코드는 절대 금지한다.
2. **Reliability over Speed:** 응답 속도가 조금 늦더라도 지수 백오프 기반의 재시도를 통해 전송 성공률을 높인다.
3. **Data Integrity:** 체크섬 검증이 되지 않은 패킷은 절대 엔티티 상태에 반영하지 않는다.
4. **Modern API:** Home Assistant의 최신 Config Flow 및 Device Registry 표준을 준수한다.

## Domain Knowledge
- **Header:** 코콤 패킷은 항상 `0xAA 0x55`로 시작한다.
- **Checksum:** 마지막 바이트는 이전 바이트들의 합산 결과물이다. (코드 내 검증 로직 필수)

## Documentation & Git Standards
1. **Comment Language:** 모든 코드 내 주석과 설명은 한국어로 작성한다. (UTF-8 encoding 필수)
2. **Commit Message:** - 반드시 한국어로 작성한다.
   - 형식: [타입] 작업내용 (예: [수정] via_device 경고 해결 및 허브 장치 추가)
3. **Docstrings:** 클래스와 함수의 Docstring은 한국어로 작성하여 가독성을 높인다.
