import 'dart:ffi';
import 'package:ffi/ffi.dart';
import 'dart:io';
import 'package:path_provider/path_provider.dart';
import 'package:flutter/foundation.dart';

import '../models/game_entry.dart';

/// Per-frame engine metrics snapshot.
class EngineMetrics {
  final double fps;
  final double frameTimeMs;
  final double cpuUsagePercent;
  final int ramUsageBytes;
  final double gpuTempCelsius;
  final int jitBlocksCompiled;
  final int jitState;
  final int gpuState;
  final int framesPresented;
  final int pm4Packets;
  final int pm4DrawAttempts;
  final int shaderAttempts;
  final int shaderCompiled;
  final int shaderFailed;
  final bool shaderBusy;
  final String gpuName;

  const EngineMetrics({
    this.fps = 0,
    this.frameTimeMs = 0,
    this.cpuUsagePercent = 0,
    this.ramUsageBytes = 0,
    this.gpuTempCelsius = 0,
    this.jitBlocksCompiled = 0,
    this.jitState = 0,
    this.gpuState = 0,
    this.framesPresented = 0,
    this.pm4Packets = 0,
    this.pm4DrawAttempts = 0,
    this.shaderAttempts = 0,
    this.shaderCompiled = 0,
    this.shaderFailed = 0,
    this.shaderBusy = false,
    this.gpuName = 'Vulkan GPU not initialized',
  });

  String get shaderStatus {
    if (shaderBusy) return 'Creating Vulkan shader module...';
    if (shaderFailed > 0) return 'Shader module failures: $shaderFailed';
    if (shaderAttempts == 0) return 'No Xenos shader requested';
    return '$shaderCompiled of $shaderAttempts Vulkan shader modules created (placeholder translator)';
  }

  String get blackScreenReason {
    if (jitState == 3) return 'JIT reported an execution error';
    if (gpuState == 3) return 'Vulkan initialization failed; check logcat';
    if (gpuState == 0) return 'Waiting for Android Vulkan surface';
    if (gpuState == 1) return 'Initializing Vulkan device and swapchain';
    if (framesPresented == 0 && pm4Packets == 0) {
      return 'No GPU commands from guest (PM4): CPU/HLE/JIT or GPU command bridge incomplete';
    }
    if (framesPresented == 0) return 'PM4 reached GPU but no completed Vulkan frame';
    if (pm4DrawAttempts == 0) return 'Vulkan presented clear frames; game draw commands absent';
    return 'PM4 draw packets received; draw execution is still a renderer stub';
  }

}

/// dart:ffi bridge to the native Xbox360 recompiler engine (C++20 NDK).
/// Loads libxbox360recomp.so and exposes JNI entry points for:
///   - XEX/STFS/ISO loading, JIT lifecycle, HLE kernel state,
///   - GPU/Vulkan surface management, per-frame metrics.
class EngineBridge {
  static EngineBridge? _instance;
  static late DynamicLibrary _lib;
  static bool _initialized = false;
  static String? _initializationError;
  static String? get initializationError => _initializationError;

  /// Singleton accessor.
  static EngineBridge get instance {
    _instance ??= EngineBridge._();
    return _instance!;
  }
  EngineBridge._();

  // ─── Native function pointers ─────────────────────────────────────────────
  static late int Function(int logLevel) _engineInit;
  static late void Function(Pointer<Utf8> game, Pointer<Utf8> save) _setDirectories;
  static late void Function() _engineShutdown;
  static late int Function(Pointer<Utf8> path, Pointer<Utf8> outTitleId, int outLen) _xexLoad;
  static late int Function(Pointer<Utf8> path, Pointer<Utf8> outTitleId, int outLen) _stfsLoad;
  static late int Function(Pointer<Utf8> path, Pointer<Utf8> outTitleId, int outLen) _isoLoad;
  static late void Function() _gameUnload;
  static late int Function(Pointer<Uint8> out, int length) _getLoadError;
  static String lastLoadError = '';
  static late int Function(int threadCount) _jitStart;
  static late void Function() _jitStop;
  static late int Function() _jitGetState;
  static late void Function() _jitPause;
  static late void Function() _jitResume;
  static late int Function(Pointer<Void> nativeWindow) _gpuSetSurface;
  static late void Function() _gpuClearSurface;
  static late double Function() _metricsGetFps;
  static late double Function() _metricsGetFrameTime;
  static late int Function() _metricsGetRamUsage;
  // CPU usage is not exported by this runtime. Do not bind an imaginary symbol.
  static late double Function() _metricsGetGpuTemp;
  static late int Function() _metricsGetJitBlocks;
  static late int Function() _metricsGpuState;
  static late int Function() _metricsJitState;
  static late int Function() _metricsGpuFrames;
  static late int Function() _metricsPm4Packets;
  static late int Function() _metricsPm4Draws;
  static late int Function() _metricsShaderAttempts;
  static late int Function() _metricsShaderCompiled;
  static late int Function() _metricsShaderFailed;
  static late int Function() _metricsShaderBusy;
  static late int Function(Pointer<Uint8> out, int capacity) _metricsGpuName;
  static late void Function(int width, int height) _settingsSetResolution;
  static late void Function(int af) _settingsSetAf;
  static late void Function(int aa) _settingsSetAa;
  static late void Function(int limit) _settingsSetFpsLimit;
  static late void Function(int threads) _settingsSetJitThreads;
  static late void Function(int pad, int buttons, int lx, int ly, int rx, int ry, int lt, int rt) _inputSetState;
  static late void Function(int pad, int lowFreq, int highFreq) _inputSetRumble;

  // ─── Input state ──────────────────────────────────────────────────────────
  int _buttonMask = 0;
  int _lx = 0, _ly = 0, _rx = 0, _ry = 0;
  int _lt = 0, _rt = 0;

  // ─── Initialization ───────────────────────────────────────────────────────
  /// Initialize once, with filesystem paths that the native HLE can access.
  /// Importing an ISO alone never triggers this 4 GiB *virtual* reservation.
  static Future<void> initialize({String? gameDirectory}) async {
    if (_initialized) return;
    _initializationError = null;
    _instance = EngineBridge._();
    if (!Platform.isAndroid) {
      _initializationError = 'Native ARM64 runtime requires Android.';
      return;
    }
    try {
      final appDir = await getApplicationDocumentsDirectory();
      final saveDir = Directory('${appDir.path}/saves');
      await saveDir.create(recursive: true);
      final gameDir = Directory(gameDirectory ?? '${appDir.path}/games');
      await gameDir.create(recursive: true);
      _lib = DynamicLibrary.open('libxbox360recomp.so');
      _bindFunctions();
      final gamePtr = gameDir.path.toNativeUtf8();
      final savePtr = saveDir.path.toNativeUtf8();
      try {
        _setDirectories(gamePtr, savePtr);
      } finally {
        calloc.free(gamePtr);
        calloc.free(savePtr);
      }
      final result = _engineInit(1);
      if (result != 0) {
        throw StateError('Native x360_engine_init returned $result '
            '(possibly guest address-space or HLE initialization failure).');
      }
      _initialized = true;
      debugPrint('[EngineBridge] Native ARM64 engine initialized');
    } catch (e, stack) {
      _initialized = false;
      _initializationError = e.toString();
      debugPrint('[EngineBridge] Native runtime initialization failed: $e');
      debugPrintStack(stackTrace: stack);
    }
  }

  static void _bindFunctions() {
    _engineInit = _lib.lookupFunction<Int32 Function(Int32), int Function(int)>('x360_engine_init');
    _engineShutdown = _lib.lookupFunction<Void Function(), void Function()>('x360_engine_shutdown');
    _setDirectories = _lib.lookupFunction<Void Function(Pointer<Utf8>, Pointer<Utf8>), void Function(Pointer<Utf8>, Pointer<Utf8>)>('x360_engine_set_directories');
    _xexLoad = _lib.lookupFunction<Int32 Function(Pointer<Utf8>, Pointer<Utf8>, Int32), int Function(Pointer<Utf8>, Pointer<Utf8>, int)>('x360_xex_load');
    _stfsLoad = _lib.lookupFunction<Int32 Function(Pointer<Utf8>, Pointer<Utf8>, Int32), int Function(Pointer<Utf8>, Pointer<Utf8>, int)>('x360_stfs_load');
    _isoLoad = _lib.lookupFunction<Int32 Function(Pointer<Utf8>, Pointer<Utf8>, Int32), int Function(Pointer<Utf8>, Pointer<Utf8>, int)>('x360_iso_load');
    _gameUnload = _lib.lookupFunction<Void Function(), void Function()>('x360_game_unload');
    _getLoadError = _lib.lookupFunction<
        Int32 Function(Pointer<Uint8>, Int32),
        int Function(Pointer<Uint8>, int)>('x360_last_load_error');
    _jitStart = _lib.lookupFunction<Int32 Function(Int32), int Function(int)>('x360_jit_start');
    _jitStop = _lib.lookupFunction<Void Function(), void Function()>('x360_jit_stop');
    _jitGetState = _lib.lookupFunction<Int32 Function(), int Function()>('x360_jit_get_state');
    _jitPause = _lib.lookupFunction<Void Function(), void Function()>('x360_jit_pause');
    _jitResume = _lib.lookupFunction<Void Function(), void Function()>('x360_jit_resume');
    _gpuSetSurface = _lib.lookupFunction<Int32 Function(Pointer<Void>), int Function(Pointer<Void>)>('x360_gpu_set_surface');
    _gpuClearSurface = _lib.lookupFunction<Void Function(), void Function()>('x360_gpu_clear_surface');
    _metricsGetFps = _lib.lookupFunction<Float Function(), double Function()>('x360_metrics_fps');
    _metricsGetFrameTime = _lib.lookupFunction<Float Function(), double Function()>('x360_metrics_frame_time');
    _metricsGetRamUsage = _lib.lookupFunction<Int64 Function(), int Function()>('x360_metrics_ram');
    _metricsGetGpuTemp = _lib.lookupFunction<Float Function(), double Function()>('x360_metrics_gpu_temp');
    _metricsGetJitBlocks = _lib.lookupFunction<Int64 Function(), int Function()>('x360_metrics_blocks_compiled');
    _metricsGpuState = _lib.lookupFunction<Int32 Function(), int Function()>('x360_metrics_gpu_state');
    _metricsJitState = _lib.lookupFunction<Int32 Function(), int Function()>('x360_metrics_jit_state');
    _metricsGpuFrames = _lib.lookupFunction<Int64 Function(), int Function()>('x360_metrics_gpu_frames');
    _metricsPm4Packets = _lib.lookupFunction<Int64 Function(), int Function()>('x360_metrics_pm4_packets');
    _metricsPm4Draws = _lib.lookupFunction<Int64 Function(), int Function()>('x360_metrics_pm4_draw_attempts');
    _metricsShaderAttempts = _lib.lookupFunction<Int64 Function(), int Function()>('x360_metrics_shader_attempts');
    _metricsShaderCompiled = _lib.lookupFunction<Int64 Function(), int Function()>('x360_metrics_shader_compiled');
    _metricsShaderFailed = _lib.lookupFunction<Int64 Function(), int Function()>('x360_metrics_shader_failed');
    _metricsShaderBusy = _lib.lookupFunction<Int32 Function(), int Function()>('x360_metrics_shader_busy');
    _metricsGpuName = _lib.lookupFunction<Int32 Function(Pointer<Uint8>, Int32), int Function(Pointer<Uint8>, int)>('x360_metrics_gpu_name');
    _settingsSetResolution = _lib.lookupFunction<Void Function(Int32, Int32), void Function(int, int)>('x360_settings_set_resolution');
    _settingsSetAf = _lib.lookupFunction<Void Function(Int32), void Function(int)>('x360_settings_set_af');
    _settingsSetAa = _lib.lookupFunction<Void Function(Int32), void Function(int)>('x360_settings_set_aa');
    _settingsSetFpsLimit = _lib.lookupFunction<Void Function(Int32), void Function(int)>('x360_settings_set_fps_limit');
    _settingsSetJitThreads = _lib.lookupFunction<Void Function(Int32), void Function(int)>('x360_settings_set_jit_threads');
    _inputSetState = _lib.lookupFunction<Void Function(Int32, Int32, Int32, Int32, Int32, Int32, Int32, Int32), void Function(int, int, int, int, int, int, int, int)>('x360_input_set_state');
    _inputSetRumble = _lib.lookupFunction<Void Function(Int32, Int32, Int32), void Function(int, int, int)>('x360_input_set_rumble');
  }

  // ─── Instance API ─────────────────────────────────────────────────────────
  int loadGame(String path, GameFormat format) {
    lastLoadError = '';
    if (!_initialized) {
      lastLoadError = _initializationError ?? 'Native engine is not initialized';
      return -1;
    }
    final pathPtr = path.toNativeUtf8();
    final titleBuf = calloc<Uint8>(64).cast<Utf8>();
    try {
      final result = switch (format) {
        GameFormat.xex  => _xexLoad(pathPtr, titleBuf, 64),
        GameFormat.stfs => _stfsLoad(pathPtr, titleBuf, 64),
        GameFormat.iso  => _isoLoad(pathPtr, titleBuf, 64),
        _               => _xexLoad(pathPtr, titleBuf, 64),
      };
      if (result != 0) {
        final errorBuf = calloc<Uint8>(1024);
        try {
          _getLoadError(errorBuf, 1024);
          lastLoadError = errorBuf.cast<Utf8>().toDartString();
          if (lastLoadError.isEmpty) {
            lastLoadError = 'Native loader returned code $result without details';
          }
        } finally {
          calloc.free(errorBuf);
        }
      }
      return result;
    } finally {
      calloc.free(pathPtr);
      calloc.free(titleBuf);
    }
  }

  int startJit([int threadCount = 4]) {
    if (!_initialized) return -1;
    return _jitStart(threadCount);
  }

  void pauseJit() {
    if (!_initialized) return;
    try { _jitPause(); } catch (_) {}
  }

  void resumeJit() {
    if (!_initialized) return;
    try { _jitResume(); } catch (_) {}
  }

  void stopJit() {
    if (!_initialized) return;
    _jitStop();
  }

  void unloadGame() {
    if (!_initialized) return;
    _gameUnload();
  }

  void buttonDown(int btn) { _buttonMask |= btn; _flushInput(); }
  void buttonUp(int btn)   { _buttonMask &= ~btn; _flushInput(); }

  void setAxis(int axis, double x, double y) {
    final ix = (x * 32767).round().clamp(-32768, 32767);
    final iy = (y * 32767).round().clamp(-32768, 32767);
    if (axis == 0) { _lx = ix; _ly = iy; } else { _rx = ix; _ry = iy; }
    _flushInput();
  }

  void setTrigger(int trigger, double value) {
    final iv = (value * 255).round().clamp(0, 255);
    if (trigger == 0) { _lt = iv; } else { _rt = iv; }
    _flushInput();
  }

  void _flushInput() {
    if (!_initialized) return;
    _inputSetState(0, _buttonMask, _lx, _ly, _rx, _ry, _lt, _rt);
  }

  EngineMetrics getMetrics() {
    if (!_initialized) return const EngineMetrics();
    final gpuBuf = calloc<Uint8>(128);
    String activeGpu = 'Vulkan GPU not initialized';
    try {
      _metricsGpuName(gpuBuf, 128);
      activeGpu = gpuBuf.cast<Utf8>().toDartString();
    } finally {
      calloc.free(gpuBuf);
    }
    return EngineMetrics(
      gpuName: activeGpu,
      gpuState: _metricsGpuState(),
      jitState: _metricsJitState(),
      framesPresented: _metricsGpuFrames(),
      pm4Packets: _metricsPm4Packets(),
      pm4DrawAttempts: _metricsPm4Draws(),
      shaderAttempts: _metricsShaderAttempts(),
      shaderCompiled: _metricsShaderCompiled(),
      shaderFailed: _metricsShaderFailed(),
      shaderBusy: _metricsShaderBusy() != 0,
      fps: _metricsGetFps(),
      frameTimeMs: _metricsGetFrameTime(),
      cpuUsagePercent: 0, // Not implemented in the native metrics API
      ramUsageBytes: _metricsGetRamUsage(),
      gpuTempCelsius: _metricsGetGpuTemp(),
      jitBlocksCompiled: _metricsGetJitBlocks(),
    );
  }

  // ─── Static convenience shims ─────────────────────────────────────────────
  static double getFps()       => _initialized ? _metricsGetFps() : 0.0;
  static double getFrameTime() => _initialized ? _metricsGetFrameTime() : 0.0;
  static int getRamUsage()     => _initialized ? _metricsGetRamUsage() : 0;
  static double getGpuTemp()   => _initialized ? _metricsGetGpuTemp() : 0.0;
  static void shutdown() { if (_initialized) { _engineShutdown(); _initialized = false; } }
  static bool get isAvailable => _initialized;
  static int loadXex(String path) => instance.loadGame(path, GameFormat.xex);
  static int loadIso(String path) => instance.loadGame(path, GameFormat.iso);
  static int loadStfs(String path) => instance.loadGame(path, GameFormat.stfs);
}
