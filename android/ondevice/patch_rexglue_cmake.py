#!/usr/bin/env python3
"""Prepare the pinned ReXGlue checkout for the experimental Android codegen bridge.

The script applies two narrow, fail-closed patches: it adds an Android JNI
shared-library target and preserves case in manifest paths (Android/Linux
filesystems are case-sensitive). The JNI source path is supplied to CMake as
XBO360_ANDROID_CODEGEN_JNI_SOURCE.
"""
from pathlib import Path
import sys


def patch_cmake(root: Path) -> bool:
    cmake = root / 'src/rexglue/CMakeLists.txt'
    if not cmake.is_file():
        raise ValueError(f'ReXGlue CMake file not found: {cmake}')
    text = cmake.read_text(encoding='utf-8')
    marker = '# XBO360_ANDROID_CODEGEN_JNI_TARGET'
    if marker in text:
        return False
    anchor = 'add_executable(rex::rexglue ALIAS rexglue)'
    if text.count(anchor) != 1:
        raise ValueError('Unexpected ReXGlue CMake structure; refusing to patch.')

    block = f'''{anchor}

{marker}
if(ANDROID AND XBO360_ANDROID_CODEGEN_JNI_SOURCE)
    add_library(xbo360_codegen_jni SHARED
        "${{XBO360_ANDROID_CODEGEN_JNI_SOURCE}}"
        "${{REXGLUE_ROOT}}/src/rexglue/commands/init_command.cpp"
        "${{REXGLUE_ROOT}}/src/rexglue/ui/ui.cpp")
    target_include_directories(xbo360_codegen_jni PRIVATE
        "${{REXGLUE_ROOT}}/src"
        "${{REXGLUE_ROOT}}/thirdparty/tomlplusplus/include"
        "${{REXGLUE_ROOT}}/thirdparty/cli11/include")
    target_link_libraries(xbo360_codegen_jni PRIVATE rexcodegen)
    target_compile_features(xbo360_codegen_jni PRIVATE cxx_std_23)
    target_link_options(xbo360_codegen_jni PRIVATE
        "-Wl,-z,max-page-size=16384"
        "-Wl,-z,common-page-size=16384")
    set_target_properties(xbo360_codegen_jni PROPERTIES
        OUTPUT_NAME xbo360_codegen_jni
        POSITION_INDEPENDENT_CODE ON)
endif()
'''
    cmake.write_text(text.replace(anchor, block), encoding='utf-8')
    return True


def patch_manifest_path_case(root: Path) -> bool:
    source = root / 'src/rexglue/commands/init_command.cpp'
    if not source.is_file():
        raise ValueError(f'ReXGlue init source not found: {source}')
    text = source.read_text(encoding='utf-8')
    marker = '// XBO360_PRESERVE_MANIFEST_PATH_CASE'
    if marker in text:
        return False

    anchor = 'std::string ManifestPath(const fs::path& target, const fs::path& base) {'
    old_target = 'return LowercaseAscii(target.generic_string());'
    old_relative = 'return LowercaseAscii(rel.generic_string());'
    if text.count(anchor) != 1 or text.count(old_target) != 1 or text.count(old_relative) != 1:
        raise ValueError('Unexpected ReXGlue ManifestPath implementation; refusing to patch.')
    text = text.replace(anchor, marker + '\n' + anchor)
    text = text.replace(old_target, 'return target.generic_string();')
    text = text.replace(old_relative, 'return rel.generic_string();')
    source.write_text(text, encoding='utf-8')
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print('usage: patch_rexglue_cmake.py REXGLUE_SOURCE_DIR', file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    try:
        changed_cmake = patch_cmake(root)
        changed_paths = patch_manifest_path_case(root)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    if changed_cmake:
        print('Enabled experimental JNI target.')
    if changed_paths:
        print('Enabled case-preserving ReXGlue manifest paths for Android/Linux.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
