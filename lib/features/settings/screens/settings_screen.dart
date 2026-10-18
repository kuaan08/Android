import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../../core/theme/app_theme.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  String _version = '';
  String _cacheSize = '...';
  bool _fpsOverlay = true;
  bool _darkStatusBar = true;
  int _logLevel = 1;
  String _gamesFolder = 'App private library (managed automatically)';
  String _savesFolder = 'App private saves (managed automatically)';
  static const MethodChannel _storageChannel =
      MethodChannel('com.viaxecomp.xbox360recomp/import');

  @override
  void initState() {
    super.initState();
    _loadInfo();
    _loadDirectories();
    _loadPreferences();
  }

  Future<void> _loadPreferences() async {
    final prefs = await SharedPreferences.getInstance();
    if (!mounted) return;
    setState(() => _fpsOverlay = prefs.getBool('global_overlay') ?? true);
  }

  Future<void> _setFpsOverlay(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('global_overlay', value);
    if (mounted) setState(() => _fpsOverlay = value);
  }

  Future<void> _loadInfo() async {
    final info = await PackageInfo.fromPlatform();
    if (!mounted) return;
    setState(() => _version = '${info.version}+${info.buildNumber}');
    _computeCacheSize();
  }

  Future<void> _computeCacheSize() async {
    try {
      final dir = await getTemporaryDirectory();
      int size = 0;
      await for (final f in dir.list(recursive: true)) {
        if (f is File) size += await f.length();
      }
      final mb = (size / (1024 * 1024)).toStringAsFixed(1);
      setState(() => _cacheSize = '$mb MB');
    } catch (_) {
      setState(() => _cacheSize = 'Unknown');
    }
  }

  Future<void> _clearCache() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Clear Cache'),
        content: const Text('This will delete compiled shader caches. Games may take longer to load after clearing.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            child: const Text('Clear'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      final dir = await getTemporaryDirectory();
      await dir.delete(recursive: true);
      await dir.create();
      setState(() => _cacheSize = '0.0 MB');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Cache cleared')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to clear cache: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.bgBase,
      body: SafeArea(
        child: CustomScrollView(
          slivers: [
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Settings', style: Theme.of(context).textTheme.displayMedium),
                    const SizedBox(height: 24),

                    // ─── DISPLAY ────────────────────────────────────────
                    _SectionLabel('Display'),
                    _SettingsCard(children: [
                      _SwitchTile(
                        icon: Icons.speed_rounded,
                        title: 'FPS Overlay',
                        subtitle: 'Show frame rate during gameplay',
                        value: _fpsOverlay,
                        onChanged: _setFpsOverlay,
                      ),
                      const _Divider(),
                      _SwitchTile(
                        icon: Icons.brightness_2_outlined,
                        title: 'Dark Status Bar',
                        subtitle: 'Dark icons in the status bar',
                        value: _darkStatusBar,
                        onChanged: (v) => setState(() => _darkStatusBar = v),
                      ),
                    ]),
                    const SizedBox(height: 16),

                    // ─── GPU STATUS ──────────────────────────────────
                    _SectionLabel('GPU / shader diagnostics'),
                    _SettingsCard(children: [
                      _SelectTile(
                        icon: Icons.monitor_heart_outlined,
                        title: 'Black-screen diagnostics',
                        subtitle: 'Real Vulkan frames, PM4 commands, JIT and shaders are shown during Play.',
                        onTap: () => showDialog(
                          context: context,
                          builder: (_) => AlertDialog(
                            title: const Text('About the black screen'),
                            content: const Text(
                              '0 FPS means no Vulkan frames were presented. '
                              'The current Xbox 360 PM4 draw execution and '
                              'Xenos shader translation are not complete. '
                              'The in-game overlay can copy real diagnostic '
                              'counters so we can investigate precisely.'),
                            actions: [
                              TextButton(onPressed: () => Navigator.pop(context),
                                child: const Text('OK')),
                            ],
                          ),
                        ),
                      ),
                      const _Divider(),
                      _SelectTile(
                        icon: Icons.memory_rounded,
                        title: 'Active Vulkan driver',
                        subtitle: 'Android system driver. Turnip selection is not wired yet.',
                        onTap: () => showDialog(
                          context: context,
                          builder: (_) => AlertDialog(
                            title: const Text('Turnip driver support'),
                            content: const Text(
                              'The current native Vulkan backend still links '
                              'to Android system Vulkan. Turnip requires '
                              'libadrenotools and a proper Vulkan function '
                              'dispatcher. A driver ZIP or a separate driver '
                              'app will not activate Turnip by itself.'),
                            actions: [
                              TextButton(onPressed: () => Navigator.pop(context),
                                child: const Text('OK')),
                            ],
                          ),
                        ),
                      ),
                    ]),
                    const SizedBox(height: 16),

                    // ─── PROCESSOR ────────────────────────────────────
                    _SectionLabel('Processor'),
                    _SettingsCard(children: [
                      _SelectTile(
                        icon: Icons.tune_rounded,
                        title: 'Log Level',
                        subtitle: _logLevelName(_logLevel),
                        onTap: () => _showLogLevelDialog(),
                      ),
                    ]),
                    const SizedBox(height: 16),

                    // ─── STORAGE ──────────────────────────────────────
                    _SectionLabel('Storage'),
                    _SettingsCard(children: [
                      _SelectTile(
                        icon: Icons.folder_outlined,
                        title: 'Games Directory',
                        subtitle: _gamesFolder,
                        onTap: () => _chooseDirectory('games'),
                      ),
                      const _Divider(),
                      _SelectTile(
                        icon: Icons.save_outlined,
                        title: 'Saves Directory',
                        subtitle: _savesFolder,
                        onTap: () => _chooseDirectory('saves'),
                      ),
                      const _Divider(),
                      _SelectTile(
                        icon: Icons.delete_sweep_outlined,
                        title: 'Clear Shader Cache',
                        subtitle: _cacheSize,
                        trailing: TextButton(
                          onPressed: _clearCache,
                          style: TextButton.styleFrom(foregroundColor: Colors.red),
                          child: const Text('Clear'),
                        ),
                        onTap: _clearCache,
                      ),
                    ]),
                    const SizedBox(height: 16),

                    // ─── COMPATIBILITY DB ─────────────────────────────
                    _SectionLabel('Compatibility'),
                    _SettingsCard(children: [
                      _SelectTile(
                        icon: Icons.cloud_sync_outlined,
                        title: 'Sync Compatibility Database',
                        subtitle: 'Update from GitHub',
                        onTap: _syncCompatDb,
                      ),
                      const _Divider(),
                      _SelectTile(
                        icon: Icons.open_in_new_rounded,
                        title: 'Browse Compatibility List',
                        subtitle: 'github.com/ViaXTrace/Xbox360RecompAndroid',
                        onTap: () => launchUrl(Uri.parse('https://github.com/ViaXTrace/Xbox360RecompAndroid/blob/main/compat/games.json')),
                      ),
                    ]),
                    const SizedBox(height: 16),

                    // ─── ABOUT ────────────────────────────────────────
                    _SectionLabel('About'),
                    _SettingsCard(children: [
                      _SelectTile(
                        icon: Icons.info_outline_rounded,
                        title: 'Xbox360RecompAndroid',
                        subtitle: 'Version $_version',
                        onTap: () => context.push('/about'),
                      ),
                      const _Divider(),
                      _SelectTile(
                        icon: Icons.code_rounded,
                        title: 'Source Code',
                        subtitle: 'Open on GitHub',
                        onTap: () => launchUrl(Uri.parse('https://github.com/kuaan08/Android')),
                      ),
                      const _Divider(),
                      _SelectTile(
                        icon: Icons.description_outlined,
                        title: 'Licenses',
                        subtitle: 'Open source components',
                        onTap: () => showLicensePage(context: context, applicationName: 'Xbox360RecompAndroid', applicationVersion: _version),
                      ),
                    ]),
                    const SizedBox(height: 100),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _loadDirectories() async {
    try {
      final appDir = await getApplicationDocumentsDirectory();
      for (final kind in ['games', 'saves']) {
        final base = Directory(appDir.path + '/' + kind);
        await base.create(recursive: true);
        final setting = await _storageChannel.invokeMapMethod<String, dynamic>(
          'getDirectory', {'kind': kind});
        if (!mounted) return;
        final name = setting?['name'] as String?;
        final subtitle = (name == null || name.isEmpty)
            ? 'App private: ' + base.path
            : 'External bookmark: ' + name + ' (not used by JIT)';
        setState(() {
          if (kind == 'games') {
            _gamesFolder = subtitle;
          } else {
            _savesFolder = subtitle;
          }
        });
      }
    } catch (error) {
      if (mounted) _showStorageError(error);
    }
  }

  void _showStorageError(Object error) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text('Storage access failed: ' + error.toString()),
      duration: const Duration(seconds: 8),
    ));
  }

  Future<void> _chooseDirectory(String kind) async {
    final answer = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(kind == 'games' ? 'Games folder' : 'Saves folder'),
        content: const Text(
          'Android 14 uses Storage Access Framework for folders. '
          'The game runtime currently needs private filesystem paths. '
          'Choosing an external folder saves an access bookmark only; it does '
          'not move existing games or saves. You do not need global storage permissions.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, 'reset'),
            child: const Text('Use internal')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, 'select'),
            child: const Text('Choose folder')),
        ],
      ),
    );
    if (answer == null) return;
    try {
      if (answer == 'select') {
        await _storageChannel.invokeMapMethod<String, dynamic>(
          'chooseDirectory', {'kind': kind});
      } else {
        await _storageChannel.invokeMethod<void>(
          'resetDirectory', {'kind': kind});
      }
      if (mounted) await _loadDirectories();
    } catch (error) {
      if (mounted) _showStorageError(error);
    }
  }

  String _logLevelName(int l) => ['Quiet', 'Error', 'Warning', 'Info', 'Debug', 'Trace'][l.clamp(0, 5)];

  Future<void> _showLogLevelDialog() async {
    final result = await showDialog<int>(
      context: context,
      builder: (_) => SimpleDialog(
        title: const Text('Log Level'),
        children: List.generate(6, (i) => SimpleDialogOption(
          onPressed: () => Navigator.pop(context, i),
          child: Text(_logLevelName(i)),
        )),
      ),
    );
    if (result != null) setState(() => _logLevel = result);
  }

  Future<void> _syncCompatDb() async {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Syncing compatibility database…')),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  final String text;
  const _SectionLabel(this.text);
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, bottom: 8),
      child: Text(
        text.toUpperCase(),
        style: const TextStyle(
          fontSize: 11, fontWeight: FontWeight.w700,
          color: AppTheme.xboxGreen, letterSpacing: 1.2,
        ),
      ),
    );
  }
}

class _SettingsCard extends StatelessWidget {
  final List<Widget> children;
  const _SettingsCard({required this.children});
  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(children: children),
    );
  }
}

class _Divider extends StatelessWidget {
  const _Divider();
  @override
  Widget build(BuildContext context) {
    return const Divider(height: 1, indent: 16, endIndent: 0);
  }
}

class _SwitchTile extends StatelessWidget {
  final IconData icon;
  final String title, subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;
  const _SwitchTile({required this.icon, required this.title, required this.subtitle, required this.value, required this.onChanged});
  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Icon(icon, color: Colors.white54, size: 22),
      title: Text(title),
      subtitle: Text(subtitle),
      trailing: Switch(value: value, onChanged: onChanged),
      onTap: () => onChanged(!value),
    );
  }
}

class _SelectTile extends StatelessWidget {
  final IconData icon;
  final String title, subtitle;
  final VoidCallback onTap;
  final Widget? trailing;
  const _SelectTile({required this.icon, required this.title, required this.subtitle, required this.onTap, this.trailing});
  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Icon(icon, color: Colors.white54, size: 22),
      title: Text(title),
      subtitle: Text(subtitle),
      trailing: trailing ?? const Icon(Icons.chevron_right_rounded, color: Colors.white24, size: 20),
      onTap: onTap,
    );
  }
}
