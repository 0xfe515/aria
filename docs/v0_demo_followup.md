# ARIA v0 Demo Follow-up 수정사항

작성일: 2026-05-27

## 목적

현재 v0 demo를 실제 시연에 더 안정적으로 사용할 수 있도록 UI 가시성, 펌웨어 운용 방식, 실행 편의성을 개선한다.

## 수정사항 목록

### 1. Demo UI bounding box 유지성 개선

#### 문제
- 현재 demo UI에서 detection box가 프레임마다 너무 쉽게 사라져 눈에 잘 띄지 않는다.
- Hailo inference 결과가 순간적으로 누락되거나 confidence가 흔들릴 때 box가 깜빡이며 시연성이 떨어진다.

#### 요구사항
- 최근 detection 결과를 짧은 시간 동안 유지하는 smoothing / persistence 로직을 추가한다.
- box가 즉시 사라지지 않고 일정 TTL 동안 유지되도록 한다.
- 유지된 box는 실제 최신 detection과 구분 가능하도록 필요 시 색상, alpha, label 등을 다르게 표시한다.

#### 구현 방향
- `aria/ui.py` 또는 별도 tracker 모듈에 detection history를 둔다.
- bbox IoU 또는 class/region 기반으로 이전 detection과 현재 detection을 연결한다.
- 예시 설정값:
  - box persistence: 0.3 ~ 1.0초
  - confidence decay 적용 가능
  - 너무 오래된 box는 제거

#### 완료 기준
- 사람/장애물 detection box가 순간 누락되어도 UI에서 과도하게 깜빡이지 않는다.
- false stale box가 장시간 남지 않는다.
- web UI와 Qt UI 모두 동일한 persistence 정책을 사용한다.

---

### 2. Pico 2W 펌웨어는 MicroPython 유지

#### 결정
- 2026-05-27 사용자 결정에 따라 v0는 MicroPython 기반 Pico 2W VL53L5CX bridge로 회귀/유지한다.
- C/C++ Pico SDK 전환은 v0 범위에서 제외한다.

#### 요구사항
- 기존 MicroPython firmware(`firmware/pico_vl53l5cx/main.py`)를 사용한다.
- 기존 binary frame format은 유지한다.
  - magic: `ARF1`
  - sequence
  - status
  - 64개 8x8 distance 값
  - checksum
- Pi-side parser(`aria/distance.py`)와 호환되어야 한다.
- `scripts/provision_pico_vl53l5cx.py`와 `scripts/verify_tof.py --require-frame`를 기본 운용/검증 경로로 둔다.

#### 완료 기준
- Pico 2W가 MicroPython 펌웨어로 USB CDC binary frame을 지속 송신한다.
- `scripts/verify_tof.py --require-frame`가 통과한다.
- C/C++ scaffold 또는 빌드 절차는 v0 필수 산출물에 포함하지 않는다.

---

### 3. Web UI와 Qt UI 이원화

#### 요구사항
- demo UI를 Web UI와 Qt UI 두 방식으로 구성한다.
- Web UI는 flag 형태로 활성화/비활성화할 수 있게 한다.
- 기본 실행 UI 정책은 추후 결정하되, 시연 환경에서 쉽게 선택 가능해야 한다.

#### 구현 방향
- 공통 demo pipeline과 UI 출력 계층을 분리한다.
  - camera capture
  - Hailo detection
  - ToF read
  - fusion/risk
  - alert state
  - UI rendering
- Web UI:
  - 기존 `aria/ui.py` 기반 유지
  - CLI flag 예시: `--web`, `--no-web`, `--web-port 8080`
- Qt UI:
  - 별도 모듈 추가 검토: `aria/qt_ui.py` 또는 `aria/ui_qt.py`
  - local HDMI/display 시연용 화면 제공
- 두 UI가 동일한 status/detection/fusion 결과를 사용하도록 한다.

#### 완료 기준
- Web UI만 실행 가능
- Qt UI만 실행 가능
- 필요 시 Web UI + Qt UI 동시 실행 가능
- Web UI 활성화 여부를 CLI flag로 지정 가능

---

### 4. 편한 실행을 위한 bash script 추가 및 Desktop symlink 생성

#### 요구사항
- 시연자가 긴 명령어를 외우지 않고 demo를 실행할 수 있도록 bash script를 추가한다.
- Raspberry Pi의 `/home/aria/desktop`에 실행용 symbolic link를 만든다.

#### 구현 방향
- repository 내 실행 스크립트 추가
  - 예: `scripts/run_demo.sh`
- 스크립트 역할:
  - repo 경로로 이동
  - 필요한 환경변수 설정 또는 `.env` 로드
  - HEF 경로, ToF 포트, camera source 기본값 지정
  - Web UI / Qt UI flag 전달
  - demo 실행
- symlink 예시:
  ```bash
  ln -sfn /home/aria/aria/scripts/run_demo.sh /home/aria/desktop/run_aria_demo.sh
  chmod +x /home/aria/aria/scripts/run_demo.sh
  ```
- 실제 Desktop 경로가 `/home/aria/Desktop`인지 `/home/aria/desktop`인지 target에서 확인 후 적용한다.

#### 완료 기준
- `scripts/run_demo.sh` 하나로 demo 실행 가능
- `/home/aria/desktop/run_aria_demo.sh` 심볼릭 링크로도 실행 가능
- 재부팅 후에도 동일하게 실행 가능
- 실행 실패 시 camera/Hailo/ToF 상태를 알기 쉬운 메시지로 출력한다.

---

## 우선순위 제안

1. Demo UI box persistence 개선
2. 실행 bash script + Desktop symlink
3. Web UI / Qt UI 이원화 구조 정리
4. Pico C/C++ 펌웨어 전환 검토 및 적용

## 검증 체크리스트

- [ ] camera live frame 표시
- [ ] Hailo YOLOv8n HEF inference 실행
- [ ] ToF binary frame 수신
- [ ] detection box가 안정적으로 유지됨
- [ ] distance/risk overlay 표시
- [ ] Web UI flag로 on/off 가능
- [ ] Qt UI 실행 가능
- [ ] `scripts/run_demo.sh`로 demo 실행 가능
- [ ] `/home/aria/desktop` symlink로 demo 실행 가능
- [ ] `scripts/verify_camera.py` 통과
- [ ] `scripts/verify_hailo.py --hef <path>` 통과
- [ ] `scripts/verify_tof.py --require-frame` 통과
