cmake_minimum_required(VERSION 3.21)
project(mallowpaper VERSION 0.4.0 LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Quick Multimedia DBus)
find_package(LayerShellQt 6.6 REQUIRED)
qt_standard_project_setup()
find_package(PkgConfig REQUIRED)
pkg_check_modules(WAYLAND REQUIRED IMPORTED_TARGET wayland-client)
find_program(WAYLAND_SCANNER wayland-scanner REQUIRED)
set(TOPLEVEL_PROTOCOL ${CMAKE_CURRENT_SOURCE_DIR}/protocols/wlr-foreign-toplevel-management-unstable-v1.xml)
add_custom_command(OUTPUT wlr-foreign-toplevel-management-client.h wlr-foreign-toplevel-management-protocol.c
    COMMAND ${WAYLAND_SCANNER} client-header ${TOPLEVEL_PROTOCOL} wlr-foreign-toplevel-management-client.h
    COMMAND ${WAYLAND_SCANNER} private-code ${TOPLEVEL_PROTOCOL} wlr-foreign-toplevel-management-protocol.c
    DEPENDS ${TOPLEVEL_PROTOCOL})
qt_add_executable(mallowpaper-monitor src/monitor.cpp wlr-foreign-toplevel-management-protocol.c
    wlr-foreign-toplevel-management-client.h)
target_include_directories(mallowpaper-monitor PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
target_link_libraries(mallowpaper-monitor PRIVATE Qt6::Core Qt6::DBus PkgConfig::WAYLAND)
target_compile_options(mallowpaper-monitor PRIVATE -Wall -Wextra -Wpedantic)
qt_add_executable(mallowpaper-renderer src/main.cpp)
qt_add_resources(mallowpaper-renderer "qml" PREFIX "/" FILES qml/Wallpaper.qml)
target_link_libraries(mallowpaper-renderer PRIVATE Qt6::Quick Qt6::Multimedia LayerShellQt::Interface)
target_compile_options(mallowpaper-renderer PRIVATE -Wall -Wextra -Wpedantic)
install(TARGETS mallowpaper-renderer mallowpaper-monitor RUNTIME DESTINATION bin)
install(DIRECTORY mallowpaper/ DESTINATION share/noctalia/plugins/mallowpaper
    PATTERN "__pycache__" EXCLUDE)
install(TARGETS mallowpaper-renderer mallowpaper-monitor RUNTIME DESTINATION share/noctalia/plugins/mallowpaper/bin)
include(CTest)
if(BUILD_TESTING)
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    add_test(NAME renderer-integration COMMAND ${Python3_EXECUTABLE}
        ${CMAKE_CURRENT_SOURCE_DIR}/tests/renderer_test.py $<TARGET_FILE:mallowpaper-renderer>)
    set_tests_properties(renderer-integration PROPERTIES TIMEOUT 45)
    add_test(NAME controller-lifecycle COMMAND ${Python3_EXECUTABLE}
        ${CMAKE_CURRENT_SOURCE_DIR}/tests/controller_test.py)
    set_tests_properties(controller-lifecycle PROPERTIES TIMEOUT 45)
    add_test(NAME pause-policies COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/policy_test.py)
    add_test(NAME effective-quality COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/optimizer_test.py)
    set_tests_properties(effective-quality PROPERTIES TIMEOUT 60)
    find_program(LUA_EXECUTABLE lua)
    if(LUA_EXECUTABLE)
        add_test(NAME service-handoff COMMAND ${LUA_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/service_test.lua
            ${CMAKE_CURRENT_SOURCE_DIR}/mallowpaper/service.luau)
    endif()
endif()
