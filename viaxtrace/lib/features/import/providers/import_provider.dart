import 'dart:io';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:crypto/crypto.dart';

import '../../../core/models/game_entry.dart';

class ImportState {
  final bool isImporting;
  final String currentStep;
  final double progress;
  final String details;
  final String? error;

  const ImportState({
    this.isImporting = false,
    this.currentStep = '',
    this.progress = 0,
    this.details = '',
    this.error,
  });

  ImportState copyWith({
    bool? isImporting, String? currentStep, double? progress,
    String? details, String? error,
  }) => ImportState(
    isImporting: isImporting ?? this.isImporting,
    currentStep: currentStep ?? this.currentStep,
    progress: progress ?? this.progress,
    details: details ?? this.details,
    error: error ?? this.error,
  );
}

final importProvider = NotifierProvider<ImportNotifier, ImportState>(ImportNotifier.new);

/// Import metadata only. Do NOT initialize the 4 GiB guest JIT or parse
/// untrusted executables in the UI process while adding a game to the library.
class ImportNotifier extends Notifier<ImportState> {
  @override
  ImportState build() => const ImportState();

  Future<GameEntry?> importGame(String sourcePath, GameFormat format, {
    String? originalName,
    String? precomputedSha256,
    int? knownSize,
    bool ownedStagingFile = false,
  }) async {
    state = const ImportState(
      isImporting: true, currentStep: 'Validating selected file...', progress: 0.10);
    final file = File(sourcePath);
    File? installedFile;
    Directory? createdDirectory;
    try {
      if (!await file.exists()) throw const FileSystemException('The selected file is not readable');
      final size = await file.length();
      if (size == 0) throw const FormatException('The selected game file is empty');
      if (knownSize != null && knownSize != size) {
        throw const FormatException('Android provided an incomplete file');
      }

      switch (format) {
        case GameFormat.iso:
          await _validateIso(file, size);
          break;
        case GameFormat.xex:
          await _validateMagic(file, const [0x58, 0x45, 0x58, 0x32], 'Not a valid XEX2 executable');
          break;
        case GameFormat.stfs:
          await _validateStfs(file);
          break;
        case GameFormat.unknown:
          throw const FormatException('Unsupported game format');
      }

      state = state.copyWith(currentStep: 'Identifying file...', progress: 0.30);
      // Never call readAsBytes() here: an Xbox 360 disc image can be several GiB.
      final hash = (precomputedSha256 != null &&
              RegExp(r'^[a-fA-F0-9]{64}$').hasMatch(precomputedSha256))
          ? precomputedSha256.toLowerCase()
          : (await sha256.bind(file.openRead()).first).toString();
      final titleId = 'IMPORT_' + hash.substring(0, 16).toUpperCase();

      final rawName = originalName ?? file.uri.pathSegments.last;
      final safeName = rawName.replaceAll(RegExp(r'[^A-Za-z0-9._ -]'), '_');
      final title = safeName.replaceFirst(RegExp(r'\.[^.]+$'), '');
      if (safeName.isEmpty || safeName == '.' || safeName == '..') {
        throw const FormatException('Invalid selected filename');
      }

      final appDir = await getApplicationDocumentsDirectory();
      final gamesDir = Directory(appDir.path + '/games');
      await gamesDir.create(recursive: true);
      createdDirectory = Directory(gamesDir.path + '/' + titleId);
      if (await createdDirectory.exists()) {
        throw const FileSystemException('This file is already imported');
      }
      await createdDirectory.create();
      installedFile = File(createdDirectory.path + '/' + safeName);
      state = state.copyWith(
        currentStep: 'Saving game to library...', progress: 0.65,
        details: 'Streaming or moving file without loading it into RAM');

      if (ownedStagingFile) {
        try {
          await file.rename(installedFile.path);
        } on FileSystemException {
          // Fallback for separate filesystems; still streams through dart:io.
          await file.copy(installedFile.path);
          await file.delete();
        }
      } else {
        await file.copy(installedFile.path);
      }

      state = const ImportState(
        isImporting: false, currentStep: 'Imported (runtime not yet validated)',
        progress: 1.0);
      return GameEntry(
        titleId: titleId,
        title: title.isEmpty ? 'Xbox 360 Game' : title,
        region: 'Unknown',
        execPath: installedFile.path,
        installDir: createdDirectory.path,
        format: format,
        compatStatus: CompatStatus.untested,
        installSizeBytes: size,
        installedAt: DateTime.now().toIso8601String(),
      );
    } catch (error) {
      // Only remove paths this operation created, never a previous game.
      if (installedFile != null && await installedFile.exists()) {
        await installedFile.delete();
      }
      if (createdDirectory != null && await createdDirectory.exists()) {
        final contents = await createdDirectory.list().toList();
        if (contents.isEmpty) await createdDirectory.delete();
      }
      state = ImportState(isImporting: false, error: error.toString());
      return null;
    } finally {
      if (ownedStagingFile && await file.exists()) {
        try { await file.delete(); } catch (_) {}
      }
    }
  }

  Future<void> _validateMagic(File file, List<int> expected, String error) async {
    final handle = await file.open();
    try {
      final magic = await handle.read(expected.length);
      if (magic.length != expected.length) throw FormatException(error);
      for (var i = 0; i < expected.length; i++) {
        if (magic[i] != expected[i]) throw FormatException(error);
      }
    } finally {
      await handle.close();
    }
  }

  Future<void> _validateStfs(File file) async {
    final handle = await file.open();
    try {
      final magic = String.fromCharCodes(await handle.read(4));
      if (magic != 'CON ' && magic != 'LIVE' && magic != 'PIRS') {
        throw const FormatException('Not a CON, LIVE, or PIRS package');
      }
    } finally {
      await handle.close();
    }
  }

  Future<void> _validateIso(File file, int size) async {
    final handle = await file.open();
    try {
      const xboxMagic = 'MICROSOFT*XBOX*MEDIA';
      for (final base in const [0, 34078720, 265879552, 405798912]) {
        final offset = base + 32 * 2048;
        if (size < offset + 2048) continue;
        await handle.setPosition(offset);
        final header = await handle.read(20);
        if (String.fromCharCodes(header) == xboxMagic) return;
      }
      if (size >= 17 * 2048) {
        await handle.setPosition(16 * 2048 + 1);
        if (String.fromCharCodes(await handle.read(5)) == 'CD001') return;
      }
      throw const FormatException(
        'No valid Xbox XDVDFS or ISO 9660 volume header found. '
        'Use a supported ISO/XISO dump.');
    } finally {
      await handle.close();
    }
  }
}
