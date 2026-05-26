# 최종작업 지침서를 만들기위한 정보 혹은 자료들을 위한 공간

# 프로젝트명
ARIA

# 프로젝트 git
github에 의해 추적되는 aria디렉토리 (디렉토리 주소: https://github.com/0xfe515/aria.git)

# 프로젝트 개요
시각장애인을 위한 장애물 탐지 스마트안경

# 작업방식
- Pi Agent로 작업함
- GPT가 계획/검수/오케스트레이션 담당
- 접근 가능한 하위 모델들에게 지시

        GPT, Claude급 모델이 아닌 Qwen2.5-coder-7B, Gemma E4B 같은 경량 로컬모델로 작업분할 <-- 경량 모델이기 때문에 명확한 지시 필요함
        OllamaCloud를 통해 제공되는 오픈소스 LLM 모델 활용가능 <-- 좀 더 큰 모델 활용가능
        하위모델 SubAgent의 작업이 끝났다면 GPT5.5를 활용하여 검토 및 테스트 후 수정사항 있다면 다시 SubAgent에 작업지시

        즉, GPT는 지휘 및 검수, 나머지 모델은 일반 작업

- 실제 개발/시연 환경 제공할 것임

    개발환경은 Raspberry pi 5 8GB모델이며
    SSH로 접근가능한 환경이며 Tailscale magic DNS(aria-core) 혹은 Tailnet IP(100.99.8.124)로 접근하도록 함

    ssh-key제공할 것임

- 검증 및 실행은 개발환경에서 진행할 것 (git clone으로 동기화)

# 부품
- raspberry pi 5 8GB * 1
- raspberry pi ai hat (hailo-8L) * 1
- [ArduCAM] Arducam 120fps Global Shutter USB Camera Board [B0332] * 1
- [Arducam] Arducam 1080P Day/Night Vision USB 카메라 모듈 [B0506] (아직없음) * 1
- [SMG-A] HC-SR04P 3.3V/5V 호환 초음파 거리센서 모듈 [SZH-USBC-004] (아직없음) * 1
- [Pololu] VL53L5CX Time-of-Flight 8×8-Zone Distance Sensor Carrier with Voltage Regulator (현재 3개 중 1개만 있음) * 3
- [SMG] BNO055 9축 IMU 가속도 센서 모듈(Qwiic) [SZH-MIN093] (아직없음) * 1

## 센서목록
- [SMG-A] HC-SR04P 3.3V/5V 호환 초음파 거리센서 모듈 [SZH-USBC-004] (아직없음) - 유리, 거울 대비
- [Pololu] VL53L5CX Time-of-Flight 8×8-Zone Distance Sensor Carrier with Voltage Regulator (현재 3개 중 1개만 있음) - ToF 거리센서 좌, 중앙, 우로 설치 계획 현재는 중앙만 있음
- [SMG] BNO055 9축 IMU 가속도 센서 모듈(Qwiic) [SZH-MIN093] (아직없음)
## 카메라목록
- [ArduCAM] Arducam 120fps Global Shutter USB Camera Board [B0332] - main
- [Arducam] Arducam 1080P Day/Night Vision USB 카메라 모듈 [B0506] (아직없음) - sub

# 연결
- raspberry pi 5 8GB <--> raspberry pi ai hat (hailo-8L)
- raspberry pi 5 8GB <--> main cam
- raspberry pi 5 8GB <--> sub cam
- raspberry pi 5 8GB <--> raspberry pi pico 2w
- raspberry pi pico 2w <--> VL53L5CX
- raspberry pi pico 2w <--> BNO055(예정)
- raspberry pi pico 2w <--> HC-SR04P(예정)

# 목표
**현재 가지고있는 부품만을 이용하여 프로젝트 실물 데모 만들기**

동작흐름은 다음과 같음
```
[카메라 부분]
1. 안경 좌, 우에 존재하는 카메라 2대를 적절하게 합성하여 하나의 영상을 만든 뒤 YOLOv8n에 입력
2. 객체인식 결과에 ToF의 거리정보 더해 최종적으로 어느 좌표에 어떤 물체가 얼마나 가까운지에 대한 정보를 만들어야함
[3D맵 부분]
1. IMU와 카메라를 이용하여 공간의 정보를 3D 맵의 형태로 만들고 정지물(안내판 등)에 대한 정보를 담고 실시간으로 이와 상호작용할 수 있어야함
[보행 부분]
1. 사용자의 보행방향을 예측해야함
2. 사전 논의된 방안으로 보통 사람은 걸을 때 진행방향을 바라보고 보행하므로 정면을 기준으로 좌, 정면, 우로 별도의 감지영역을 만들고 이를 필두로 위험도를 측정함
3. 사용자의 상태 (가만히 서 있음, 이동 중)을 구별하여 그에 맞는 경보거리를 설정해야함
[알림 부분]
1. 종합된 정보로 정면에서 점점 커지는 물체가 가까운 물체가 좌, 우에서 중앙으로 넘어오는 경우, 빠르게 크기가 변화하는 물체 (속도가 빠른 물체)에 대해 사용자에게 경보해야함. 경보 방법에 대해서는 추후 햅틱 진동모터나, TTS를 활용하는 방안을 고려 중
2. 안내문으로 판별되는 경우 안의 내용을 읽을 수 있어야 함
3. 엘레베이터에서 버튼들의 위치를 파악하고 사용자에게 방향을 진동 (좌, 우)로 알려주며 사용자의 행동에 따라 강도를 조절하거나 양쪽을 울리는 등 (목표가 바로앞에 있는 경우) 정보를 제공해야함
4. 주변 상황을 종합하여 현장 안전도를 측정하고 일정 수치 보다 높다면 사용자에게 주의 음성을 내보내야함
5. 안내판 혹은 엘레베이터 버튼 등에 접근할 때는 거리 경보 알림을 꺼야함
```


# 지시사항
- 실행 및 검증의 경우 local이 아닌 제공되는 실제환경 aria-core에서 실행할 것
- 데모이므로 실제 완전한 임베디드(cli)환경이 아닌 GUI환경임 이를 고려할 것 (렌더링 리소스또한 고려하라는 뜻)
- 표시 형식에 대해서는 따로 형태는 지정하지 않으나 본래의 이미지, 그리고 객체인식 및 센서들에서 종합된 데이터들이 표시된 이미지 그리고 택스트로 전달할 것 있으며 포함시키기
- 추후 추가될 부품에 대해서는 제외하고 작업하지 않고 추후 추가될 것을 고려하여 작업할 것 (미리 함수작성 혹은 디렉토리,코드구조 미리 생성), 2개 혹은 그 이상의 갯수로 같이 융합하여 동작하는 로직의 경우 인식되는 장치에 따라 모드를 전환할 수 있게 함수를 작성할 것
- subagent에 한번에 많은 작업을 지시하지 말 것
- subagent에 작업을 지시할 때는 지시사항과 제한사항을 함께 지시해야함