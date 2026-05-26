cmake_minimum_required(VERSION 3.13)

include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(aria_pico_vl53l5cx_bridge C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(aria_pico_vl53l5cx_bridge
    main.cpp
)

target_include_directories(aria_pico_vl53l5cx_bridge PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}
    # Add the ST/Pololu VL53L5CX ULD include directory here when vendored or
    # installed outside the repository. Do not commit generated driver blobs
    # unless their license/source has been reviewed.
)

target_link_libraries(aria_pico_vl53l5cx_bridge
    pico_stdlib
    hardware_i2c
)

pico_enable_stdio_usb(aria_pico_vl53l5cx_bridge 1)
pico_enable_stdio_uart(aria_pico_vl53l5cx_bridge 0)
pico_add_extra_outputs(aria_pico_vl53l5cx_bridge)
