# LineForge — native core (CMake path).
# The add-on targets Blender 5.2 = CPython 3.13; the module must be built against the very
# same Python ABI that Blender ships (Windows: MSVC or MinGW-w64; Linux/macOS: matching 3.13).
#
#   cmake -S . -B build/cmake -DPython_EXECUTABLE=<blender python> -Dpybind11_DIR=<...>
#   cmake --build build/cmake --config Release
#
# The output is copied to addon/lineforge/bin/<platform>/ so Blender can import it.
cmake_minimum_required(VERSION 3.18)
project(lineforge_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

find_package(Python 3.13 REQUIRED COMPONENTS Development.Module)
find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(lineforge_core src/core.cpp src/module.cpp)
target_include_directories(lineforge_core PRIVATE src)
target_link_libraries(lineforge_core PRIVATE Python::Module)
if(MSVC)
  target_compile_options(lineforge_core PRIVATE /W3 /permissive-)
  target_compile_definitions(lineforge_core PRIVATE _hypot=hypot)
else()
  target_compile_options(lineforge_core PRIVATE -Wall -Wextra -Wno-unused-parameter)
endif()

# Place the module where the add-on expects it: bin/<platform>/lineforge_core.<ext>
if(WIN32 AND CMAKE_SIZEOF_VOID_P EQUAL 8)
  set(LF_TAG "win64")
elseif(APPLE)
  set(LF_TAG "macos-x64")
  if(CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64")
    set(LF_TAG "macos-arm64")
  endif()
elseif(UNIX)
  if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
    set(LF_TAG "linux-arm64")
  else()
    set(LF_TAG "linux-x64")
  endif()
else()
  set(LF_TAG "unknown")
endif()

set(LF_BIN_DIR "${CMAKE_CURRENT_SOURCE_DIR}/addon/lineforge/bin/${LF_TAG}")
if(WIN32)
  set(LF_OUT "${LF_BIN_DIR}/lineforge_core.pyd")
else()
  set(LF_OUT "${LF_BIN_DIR}/lineforge_core.so")
endif()

add_custom_command(TARGET lineforge_core POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E make_directory "${LF_BIN_DIR}"
  COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:lineforge_core> "${LF_OUT}"
  COMMENT "Copying lineforge_core into addon/lineforge/bin/${LF_TAG}")

message(STATUS "LineForge core -> ${LF_OUT}")
