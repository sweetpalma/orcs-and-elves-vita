add_library(oecore STATIC bar.c pmd.c qcelp.c moddata.c)
add_library(oe2core ALIAS oecore)
target_include_directories(oecore PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(oecore PUBLIC PkgConfig::ZLIB)

add_executable(oe2tool tools/oe2tool.c)
target_link_libraries(oe2tool PRIVATE oecore)

set(HOST_SOURCES
	${CMAKE_CURRENT_SOURCE_DIR}/../../host/lighting.c
	${CMAKE_CURRENT_SOURCE_DIR}/../../host/presentation.c
	${CMAKE_CURRENT_SOURCE_DIR}/../../host/standalone_bridge.c
)

# OE1 (Orcs & Elves)
file(GLOB OE1_GAME_SOURCES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/oe1/*.c)
add_executable(oe1
	main.c
	platform_sdl.c
	${HOST_SOURCES}
	${OE1_GAME_SOURCES}
)
target_include_directories(oe1 PRIVATE
	${CMAKE_CURRENT_SOURCE_DIR}
	${CMAKE_CURRENT_SOURCE_DIR}/oe1
	${CMAKE_CURRENT_SOURCE_DIR}/../../host
)
target_compile_definitions(oe1 PRIVATE OE2_STANDALONE_BRIDGE OE2_NO_SPRITE_SHADOWS GAME_OE1=1)
target_link_libraries(oe1 PRIVATE oecore PkgConfig::SDL2 m)

# OE2 (Orcs & Elves II)
file(GLOB OE2_GAME_SOURCES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/oe2/*.c)
add_executable(oe2
	main.c
	platform_sdl.c
	${HOST_SOURCES}
	${OE2_GAME_SOURCES}
)
target_include_directories(oe2 PRIVATE
	${CMAKE_CURRENT_SOURCE_DIR}
	${CMAKE_CURRENT_SOURCE_DIR}/oe2
	${CMAKE_CURRENT_SOURCE_DIR}/../../host
)
target_compile_definitions(oe2 PRIVATE OE2_STANDALONE_BRIDGE OE2_NO_SPRITE_SHADOWS GAME_OE2=1)
target_link_libraries(oe2 PRIVATE oecore PkgConfig::SDL2 m)

if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
	# The original is ARM code: two's-complement wraparound in its fixed-point math (-fwrapv), and plain
	# char is unsigned in the ARM ABI (-funsigned-char).
	target_compile_options(oe1 PRIVATE -fwrapv -funsigned-char -Wall -Wno-unused-parameter -Wno-unused-variable -Wno-unused-function)
	target_compile_options(oe2 PRIVATE -fwrapv -funsigned-char -Wall -Wno-unused-parameter -Wno-unused-variable -Wno-unused-function)
endif()

if(OE2_SANITIZE)
	foreach(t oecore oe2tool oe1 oe2)
		target_compile_options(${t} PRIVATE -fsanitize=address,undefined -fno-sanitize=shift-base -fno-omit-frame-pointer)
		target_link_options(${t} PRIVATE -fsanitize=address,undefined)
	endforeach()
endif()
