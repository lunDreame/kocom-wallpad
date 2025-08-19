[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Kocom Wallpad Integration for Home Assistant
Home Assistant를 위한 Kocom Wallpad 통합구성요소

## 기여
문제가 있나요? [Issues](https://github.com/lunDreame/kocom-wallpad/issues) 탭에 작성해 주세요.

- 더 좋은 아이디어가 있나요? [Pull requests](https://github.com/lunDreame/kocom-wallpad/pulls)로 공유해 주세요!
- 이 통합을 사용하면서 발생하는 문제에 대해서는 책임지지 않습니다.

도움이 되셨나요? [카카오페이](https://qr.kakaopay.com/FWDWOBBmR) [토스](https://toss.me/lundreamer)

## 설치
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=lunDreame&repository=kocom-wallpad&category=Integration)

이 통합을 설치하려면 이 GitHub Repo를 HACS Custom Repositories에 추가하거나 위의 배지를 클릭하세요. 설치 후 HomeAssistant를 재부팅하세요.

1. **기기 및 서비스** 메뉴에서 **통합구성요소 추가하기**를 클릭합니다.
2. **브랜드 이름 검색** 탭에 `코콤 월패드`을 입력하고 검색 결과에서 클릭합니다.
3. 아래 설명에 따라 설정을 진행합니다:
   - 호스트: EW11 장치의 IP 주소
   - 포트: EW11 장치의 포트 (기본값: 8899)
4. 설정이 완료된 후, 컴포넌트가 로드되면 생성된 기기를 사용하실 수 있습니다.

### 준비
- 기본적인 환경에선 EW11 장치 하나 필요 추가적인 인터폰 제어 시에는 기존 장치 포함 하나 더 필요
- 인터폰 결선의 경우 [해당](https://blog.oriang.net/45) 링크 참조

## 기능

| 기기       | 지원  | 속성                           |
|-----------|------|-------------------------------|
| 조명 (디밍) | O    |                               |
| 일괄소등    | O    |                               |
| 콘센트      | O    |                               |
| 난방       | O    | 외출 모드                        |
| 에어컨     | O    |                                |
| 환기       | O    |                                |
| 가스       | O    | 잠금만 지원                       |
| 실내 공기질  | O    |                                |
| 모션(현관)  | O    |                                |
| 인터폰      | O    |                                 |
| 엘리베이터   | O    | 방향, 층수                       |

- **초기 장치 추가 시에는 최초 한번은 장치를 ON/OFF 하셔야 합니다.**
- 엘리베이터의 경우 현관 스위치가 있는 경우 현관 스위치에서 호출하셔야 정상적으로 등록됩니다.
- 장치 추가 등은 이슈 또는 메일로 문의 부탁드립니다.

## 디버깅
- 문제 파악을 위해 아래 코드를 `configuration.yaml` 파일에 추가 후 HomeAssistant를 재시작해 주세요.
- 디버깅 외에는 활성화하지 마세요.

문의 [이메일](mailto:lundreame34@gmail.com)로 연락 부탁드립니다.

```yaml
logger:
  default: info
  logs:
    custom_components.kocom_wallpad: debug
```

## 라이선스
Kocom WallPad 통합은 [Apache License](./LICENSE)를 따릅니다.
