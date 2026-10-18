import 'package:flutter_test/flutter_test.dart';
import 'package:xbox360recomp_android/core/native/engine_bridge.dart';

void main() {
  test('Zero PM4 is a CPU/HLE/GPU bridge issue, not shader compilation', () {
    const m = EngineMetrics(jitState: 1, gpuState: 2, jitBlocksCompiled: 1);
    expect(m.blackScreenReason, contains('No GPU commands'));
    expect(m.shaderStatus, 'No Xenos shader requested');
    expect(m.framesPresented, 0);
  });

  test('Vulkan failure and missing surface are differentiated', () {
    expect(const EngineMetrics(jitState: 1, gpuState: 3).blackScreenReason,
        contains('Vulkan initialization failed'));
    expect(const EngineMetrics(jitState: 1, gpuState: 0).blackScreenReason,
        contains('Waiting for Android Vulkan surface'));
  });

  test('Shader status reflects actual creation results, never invented percent', () {
    const working = EngineMetrics(shaderAttempts: 2, shaderCompiled: 1,
        shaderBusy: true);
    expect(working.shaderStatus, contains('Creating Vulkan shader module'));
    const failed = EngineMetrics(shaderAttempts: 2, shaderCompiled: 1,
        shaderFailed: 1);
    expect(failed.shaderStatus, contains('Shader module failures: 1'));
  });

  test('Presenting only a clear frame is not game drawing', () {
    const m = EngineMetrics(gpuState: 2, jitState: 1,
        pm4Packets: 5, framesPresented: 1, pm4DrawAttempts: 0);
    expect(m.blackScreenReason, contains('draw commands absent'));
  });
}
