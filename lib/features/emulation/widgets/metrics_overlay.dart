import 'dart:async';
import 'package:flutter/material.dart';
import '../../../core/native/engine_bridge.dart';
import '../../../core/theme/app_theme.dart';

class MetricsOverlay extends StatefulWidget {
  const MetricsOverlay({super.key});
  @override
  State<MetricsOverlay> createState() => _MetricsOverlayState();
}

class _MetricsOverlayState extends State<MetricsOverlay> {
  Timer? _timer;
  EngineMetrics _metrics = const EngineMetrics();

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(milliseconds: 500), (_) {
      final m = EngineBridge.instance.getMetrics();
      if (mounted) setState(() => _metrics = m);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Color _fpsColor(double fps) {
    if (fps >= 55) return AppTheme.statusPlayable;
    if (fps >= 30) return AppTheme.statusBoots;
    return AppTheme.statusNothing;
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(maxWidth: 310),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.black.withAlpha(160),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.white.withAlpha(20)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          _MetricRow(
            label: 'FPS',
            value: _metrics.fps.toStringAsFixed(1),
            color: _fpsColor(_metrics.fps),
            bold: true,
          ),
          const SizedBox(height: 3),
          _MetricRow(label: 'Frame', value: '${_metrics.frameTimeMs.toStringAsFixed(1)}ms'),
          _MetricRow(label: 'CPU', value: '${_metrics.cpuUsagePercent.toStringAsFixed(0)}%'),
          _MetricRow(label: 'RAM', value: '${(_metrics.ramUsageBytes / 1024 / 1024).toStringAsFixed(0)}MB'),
          if (_metrics.gpuTempCelsius > 0)
            _MetricRow(label: 'GPU', value: '${_metrics.gpuTempCelsius.toStringAsFixed(0)}°C'),
          _MetricRow(label: 'JIT', value: '${_metrics.jitBlocksCompiled} blocks / state ${_metrics.jitState}'),
          _MetricRow(label: 'VK', value: _metrics.gpuState == 2 ? 'Ready' : _metrics.gpuState == 3 ? 'Failed' : 'Not ready'),
          _MetricRow(label: 'Frames', value: '${_metrics.framesPresented} presented'),
          _MetricRow(label: 'PM4', value: '${_metrics.pm4Packets} packets / ${_metrics.pm4DrawAttempts} draw requests'),
          _MetricRow(label: 'Shader', value: '${_metrics.shaderCompiled}/${_metrics.shaderAttempts} modules, ${_metrics.shaderFailed} failed'),
          if (_metrics.shaderBusy)
            const Text('Compiling a Vulkan shader module...',
                style: TextStyle(fontSize: 10, color: Colors.amber)),
          const SizedBox(height: 3),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 290),
            child: Text(_metrics.gpuName,
                maxLines: 2, overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 9, color: Colors.white54)),
          ),
        ],
      ),
    );
  }
}

class _MetricRow extends StatelessWidget {
  final String label, value;
  final Color? color;
  final bool bold;
  const _MetricRow({required this.label, required this.value, this.color, this.bold = false});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          '$label ',
          style: const TextStyle(fontSize: 10, color: Colors.white38, fontFamily: 'monospace'),
        ),
        Text(
          value,
          style: TextStyle(
            fontSize: 10,
            color: color ?? Colors.white70,
            fontFamily: 'monospace',
            fontWeight: bold ? FontWeight.w700 : FontWeight.normal,
          ),
        ),
      ],
    );
  }
}
