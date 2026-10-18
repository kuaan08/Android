"""Protect the launcher from eager JNI startup and Android process-fatal crashes."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CodegenProcessIsolationTests(unittest.TestCase):
    def test_launcher_never_loads_rexglue_or_initializes_jni(self):
        source = (ROOT / "android/LauncherActivity.java").read_text(encoding="utf-8")
        self.assertNotIn("CodegenBridge.initialize(", source)
        self.assertNotIn("System.loadLibrary(", source)
        self.assertNotIn("CodegenBridge.initAndRunCodegenAsync(", source)
        self.assertIn("bindService(service, codegenConnection, Context.BIND_AUTO_CREATE)", source)
        self.assertIn("onServiceDisconnected(ComponentName name)", source)

    def test_jni_initializes_only_in_separate_process_service(self):
        service = (ROOT / "android/CodegenService.java").read_text(encoding="utf-8")
        builder = (ROOT / "android_build.py").read_text(encoding="utf-8")
        self.assertIn("CodegenBridge.initialize(CodegenService.this)", service)
        self.assertIn('android:process=":codegen"', builder)
        self.assertIn('android:exported="false"', builder)
        self.assertIn("if codegen_runtime else ''", builder)
        self.assertIn('"android/CodegenService.java"', builder)

    def test_service_reports_failure_and_success_separately(self):
        service = (ROOT / "android/CodegenService.java").read_text(encoding="utf-8")
        self.assertIn("respond(client, COMPLETE, error);", service)
        self.assertIn("respond(client, COMPLETE, e.toString());", service)
        self.assertIn("respond(client, PROGRESS", service)


if __name__ == "__main__":
    unittest.main()
