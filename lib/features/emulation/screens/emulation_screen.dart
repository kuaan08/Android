import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:go_router/go_router.dart';

import '../../../core/native/engine_bridge.dart';
import '../../../core/theme/app_theme.dart';
import '../../library/providers/library_provider.dart';
import '../widgets/metrics_overlay.dart';
import '../widgets/touch_controls_overlay.dart';

class EmulationScreen extends ConsumerStatefulWidget {
  final String titleId;
  const EmulationScreen({super.key, required this.titleId});

  @override
  ConsumerState<EmulationScreen> createState() => _EmulationScreenState();
}

class _EmulationScreenState extends ConsumerState<EmulationScreen>
    with WidgetsBindingObserver {
  bool _showControls = true;
  bool _showMetrics = true;
  bool _showDiagnostics = true;
  EngineMetrics _nativeMetrics = const EngineMetrics();
  Timer? _diagnosticTimer;
  bool _showMenu = false;
  bool _isRunning = false;
  bool _isPaused = false;
  String _statusMessage = 'Initializing…';
  Timer? _playtimeTimer;
  int _sessionSeconds = 0;
  Timer? _menuHideTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _enterFullscreen();
    _startEmulation();
  }

  @override
  void dispose() {
    _diagnosticTimer?.cancel();
    _playtimeTimer?.cancel();
    _menuHideTimer?.cancel();
    _stopEmulation();
    _exitFullscreen();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused && _isRunning) {
      _pauseEmulation();
    } else if (state == AppLifecycleState.resumed && _isPaused) {
      _resumeEmulation();
    }
  }

  void _enterFullscreen() {
    SystemChrome.setPreferredOrientations([
      DeviceOrientation.landscapeLeft,
      DeviceOrientation.landscapeRight,
    ]);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  }

  void _exitFullscreen() {
    SystemChrome.setPreferredOrientations([
      DeviceOrientation.portraitUp,
      DeviceOrientation.landscapeLeft,
      DeviceOrientation.landscapeRight,
    ]);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  }

  Future<void> _startEmulation() async {
    setState(() => _statusMessage = 'Loading game…');
    try {
      final matches = ref.read(libraryProvider).valueOrNull
          ?.where((g) => g.titleId == widget.titleId);
      if (matches == null || matches.isEmpty) {
        if (mounted) _showError('Game not found in the imported library.');
        return;
      }
      final game = matches.first;
      final prefs = await SharedPreferences.getInstance();
      if (!mounted) return;
      final jitThreads = (prefs.getInt('game_${widget.titleId}_jit_threads') ?? 2).clamp(1, 6);
      setState(() {
        _showMetrics = prefs.getBool('global_overlay') ?? true;
        _showDiagnostics = prefs.getBool('game_${widget.titleId}_gpu_diagnostics') ?? true;
        _statusMessage = 'Initializing native runtime…';
      });
      await EngineBridge.initialize(gameDirectory: game.installDir);
      if (!mounted) return;
      if (!EngineBridge.isAvailable) {
        if (mounted) _showError('Native ARM64 runtime could not initialize.\n\n' +
            (EngineBridge.initializationError ?? 'Unknown native error') +
            '\n\nThe app contains the ARM64 library; this error is not proof your processor is unsupported.');
        return;
      }
      setState(() => _statusMessage = 'Parsing executable…');
      final bridge = EngineBridge.instance;
      int result = bridge.loadGame(game.execPath, game.format);

      if (result != 0) {
        if (mounted) _showError('Could not prepare Xbox 360 executable (error $result).\n\n' +
            EngineBridge.lastLoadError +
            '\n\nThe ARM64 runtime is present; XEX2 compatibility and JIT are still experimental.');
        return;
      }

      setState(() => _statusMessage = 'Starting JIT engine…');
      result = bridge.startJit(jitThreads);
      if (result != 0) {
        if (mounted) _showError('JIT engine failed to start (error $result)');
        return;
      }

      setState(() {
        _statusMessage = 'JIT started; waiting for real GPU frames';
        _isRunning = true;
      });

      _playtimeTimer = Timer.periodic(const Duration(seconds: 1), (_) {
        _sessionSeconds++;
      });
      _diagnosticTimer?.cancel();
      _diagnosticTimer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (!mounted || !_isRunning) return;
        final snapshot = EngineBridge.instance.getMetrics();
        setState(() => _nativeMetrics = snapshot);
      });
    } catch (e) {
      if (mounted) _showError('$e');
    }
  }

  void _pauseEmulation() {
    if (!_isRunning || _isPaused) return;
    EngineBridge.instance.pauseJit();
    setState(() => _isPaused = true);
    _playtimeTimer?.cancel();
  }

  void _resumeEmulation() {
    if (!_isPaused) return;
    EngineBridge.instance.resumeJit();
    setState(() => _isPaused = false);
    _playtimeTimer = Timer.periodic(const Duration(seconds: 1), (_) => _sessionSeconds++);
  }

  void _stopEmulation() {
    _diagnosticTimer?.cancel();
    if (_isRunning) {
      EngineBridge.instance.stopJit();
      EngineBridge.instance.unloadGame();
      _savePlaytime();
    }
  }

  void _savePlaytime() {
    if (_sessionSeconds > 0) {
      ref.read(libraryProvider.notifier).addPlaytime(widget.titleId, _sessionSeconds);
    }
  }

  void _showError(String message) {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => AlertDialog(
        title: const Text('Emulation Error'),
        content: Text(message),
        actions: [
          TextButton(
            onPressed: () { Navigator.pop(context); context.pop(); },
            child: const Text('Back to Library'),
          ),
        ],
      ),
    );
  }

  void _copyNativeReport() {
    final m = _nativeMetrics;
    final report = [
      'Xbox360RecompAndroid ARM64 diagnostics',
      'Title: ${widget.titleId}',
      'Native JIT state: ${m.jitState}',
      'JIT blocks compiled: ${m.jitBlocksCompiled}',
      'GPU/Vulkan status: ${m.gpuState} (0=idle,1=initializing,2=ready,3=failed)',
      'Selected GPU: ${m.gpuName}',
      'Vulkan frames presented: ${m.framesPresented}',
      'PM4 packets: ${m.pm4Packets}',
      'PM4 draw requests (STUB): ${m.pm4DrawAttempts}',
      'Shader requests: ${m.shaderAttempts}',
      'Vulkan shader modules created (placeholder): ${m.shaderCompiled}',
      'Shader failures: ${m.shaderFailed}',
      'Shader busy: ${m.shaderBusy}',
      'FPS (presented frames): ${m.fps}',
      'RAM: ${m.ramUsageBytes} bytes',
      'Renderer limitation: Xenos draw/PM4 dispatch still incomplete.',
      'Turnip override: not installed or supported in this build.',
    ].join('\n');
    Clipboard.setData(ClipboardData(text: report));
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Native diagnostic counters copied')),
    );
  }

  void _toggleMenu() {
    setState(() => _showMenu = !_showMenu);
    if (_showMenu) {
      _menuHideTimer?.cancel();
      _menuHideTimer = Timer(const Duration(seconds: 5), () {
        if (mounted) setState(() => _showMenu = false);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: GestureDetector(
        onTap: _toggleMenu,
        child: Stack(
          children: [
            // Native rendering surface
            if (_isRunning) const _GameSurface(),

            // Loading overlay
            if (!_isRunning)
              Container(
                color: Colors.black,
                child: Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const CircularProgressIndicator(color: AppTheme.xboxGreen, strokeWidth: 3),
                      const SizedBox(height: 20),
                      Text(_statusMessage,
                          style: const TextStyle(color: Colors.white70, fontSize: 15, fontWeight: FontWeight.w500)),
                    ],
                  ),
                ),
              ),

            // Paused overlay
            if (_isPaused)
              Container(
                color: Colors.black54,
                child: Center(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 20),
                    decoration: BoxDecoration(
                      color: AppTheme.surface,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: AppTheme.border),
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.pause_circle_filled, size: 56, color: AppTheme.xboxGreen),
                        const SizedBox(height: 12),
                        const Text('Paused', style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w700)),
                        const SizedBox(height: 20),
                        ElevatedButton.icon(
                          onPressed: _resumeEmulation,
                          icon: const Icon(Icons.play_arrow_rounded),
                          label: const Text('Resume'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),

            // Explain the black screen, rather than claiming JIT startup
            // means the game is rendering. Copy exports counters, not ROM data.
            if (_isRunning && _showDiagnostics && _sessionSeconds >= 4 &&
                (_nativeMetrics.framesPresented == 0 ||
                 _nativeMetrics.pm4DrawAttempts == 0))
              Positioned(
                top: 14,
                left: 310,
                right: 155,
                child: Center(child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 360),
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.black.withAlpha(225),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: Colors.amber.withAlpha(130)),
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('GPU / JIT diagnostics',
                            style: TextStyle(color: Colors.amber, fontWeight: FontWeight.bold)),
                        const SizedBox(height: 6),
                        Text(_nativeMetrics.blackScreenReason,
                            style: const TextStyle(color: Colors.white70, fontSize: 11)),
                        const SizedBox(height: 5),
                        Text(_nativeMetrics.shaderStatus,
                            style: const TextStyle(color: Colors.white54, fontSize: 10)),
                        Align(
                          alignment: Alignment.centerRight,
                          child: TextButton.icon(
                            onPressed: _copyNativeReport,
                            icon: const Icon(Icons.copy, size: 15),
                            label: const Text('Copy diagnostic'),
                          ),
                        ),
                      ],
                    ),
                  ),
                )),
              ),

            // Touch controls
            if (_isRunning && _showControls && !_isPaused)
              const TouchControlsOverlay(),

            // Metrics overlay
            if (_isRunning && _showMetrics)
              const Positioned(top: 12, left: 12, child: MetricsOverlay()),

            // In-game menu
            if (_showMenu)
              _InGameMenu(
                isPaused: _isPaused,
                showControls: _showControls,
                showMetrics: _showMetrics,
                onPause: () { _toggleMenu(); _pauseEmulation(); },
                onResume: () { _toggleMenu(); _resumeEmulation(); },
                onToggleControls: () => setState(() => _showControls = !_showControls),
                onToggleMetrics: () => setState(() => _showMetrics = !_showMetrics),
                onGameSettings: () {
                  _pauseEmulation();
                  context.push('/game-settings/${widget.titleId}');
                },
                onControlsEditor: () {
                  _pauseEmulation();
                  context.push('/controls-editor');
                },
                onQuit: () {
                  showDialog(
                    context: context,
                    builder: (_) => AlertDialog(
                      title: const Text('Quit Game?'),
                      content: const Text('Unsaved progress will be lost.'),
                      actions: [
                        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
                        TextButton(
                          onPressed: () { Navigator.pop(context); context.pop(); },
                          style: TextButton.styleFrom(foregroundColor: Colors.red),
                          child: const Text('Quit'),
                        ),
                      ],
                    ),
                  );
                },
              ),
          ],
        ),
      ),
    );
  }
}

class _GameSurface extends StatelessWidget {
  const _GameSurface();
  @override
  Widget build(BuildContext context) {
    return const AndroidView(
      viewType: 'xbox360recomp/game_surface',
      layoutDirection: TextDirection.ltr,
    );
  }
}

class _InGameMenu extends StatelessWidget {
  final bool isPaused, showControls, showMetrics;
  final VoidCallback onPause, onResume, onToggleControls, onToggleMetrics;
  final VoidCallback onGameSettings, onControlsEditor, onQuit;

  const _InGameMenu({
    required this.isPaused, required this.showControls, required this.showMetrics,
    required this.onPause, required this.onResume, required this.onToggleControls,
    required this.onToggleMetrics, required this.onGameSettings,
    required this.onControlsEditor, required this.onQuit,
  });

  @override
  Widget build(BuildContext context) {
    return Positioned(
      top: 0, right: 0, bottom: 0,
      child: Container(
        width: 220,
        color: Colors.black87,
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('Menu', style: TextStyle(color: Colors.white70, fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1.2)),
                const SizedBox(height: 16),
                if (!isPaused)
                  _MenuButton(icon: Icons.pause_rounded, label: 'Pause', onTap: onPause)
                else
                  _MenuButton(icon: Icons.play_arrow_rounded, label: 'Resume', color: AppTheme.xboxGreen, onTap: onResume),
                const SizedBox(height: 8),
                _MenuToggle(icon: Icons.gamepad_outlined, label: 'Touch Controls', value: showControls, onChanged: (_) => onToggleControls()),
                _MenuToggle(icon: Icons.speed_outlined, label: 'FPS Overlay', value: showMetrics, onChanged: (_) => onToggleMetrics()),
                const SizedBox(height: 8),
                _MenuButton(icon: Icons.tune_rounded, label: 'Game Settings', onTap: onGameSettings),
                _MenuButton(icon: Icons.gamepad_rounded, label: 'Edit Controls', onTap: onControlsEditor),
                const Spacer(),
                _MenuButton(icon: Icons.exit_to_app_rounded, label: 'Quit Game', color: Colors.red, onTap: onQuit),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _MenuButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color? color;
  final VoidCallback onTap;
  const _MenuButton({required this.icon, required this.label, this.color, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return ListTile(
      dense: true,
      leading: Icon(icon, color: color ?? Colors.white70, size: 20),
      title: Text(label, style: TextStyle(color: color ?? Colors.white, fontSize: 13, fontWeight: FontWeight.w500)),
      onTap: onTap,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
    );
  }
}

class _MenuToggle extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool value;
  final ValueChanged<bool> onChanged;
  const _MenuToggle({required this.icon, required this.label, required this.value, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return ListTile(
      dense: true,
      leading: Icon(icon, color: Colors.white70, size: 20),
      title: Text(label, style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w500)),
      trailing: Switch(value: value, onChanged: onChanged),
      onTap: () => onChanged(!value),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
    );
  }
}

