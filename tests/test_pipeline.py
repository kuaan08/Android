"""Contract tests plus optional real-SDK integration; no commercial input files."""
import contextlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import xbo360 as x


def make_xex(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack(">4s5I", b"XEX2", 1, 24, 0, 0, 0) + b"MZ" + bytes(100))


class HeaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "Default.xex"

    def test_header_fields_are_big_endian(self):
        make_xex(self.file)
        h = x.inspect_xex(self.file)
        self.assertEqual(h["module_flags"], 1)
        self.assertEqual(h["image_offset"], 24)

    def test_rejects_switch_and_short_headers(self):
        for data in (b"NSO0" + bytes(50), b"XEX2", bytes(24)):
            self.file.write_bytes(data)
            with self.assertRaises(x.RecompError):
                x.inspect_xex(self.file)

    def test_rejects_truncated_table_and_invalid_image_offset(self):
        for count, offset in [(3, 24), (0, 0), (0, 999), (0xFFFFFFFF, 24)]:
            self.file.write_bytes(struct.pack(">4s5I", b"XEX2", 1, offset, 0, 0, count) + bytes(20))
            with self.assertRaises(x.RecompError):
                x.inspect_xex(self.file)

    def test_invalid_project_names(self):
        for name in ("", "../game", "a;exit", "1game", "Game", "a" * 65):
            with self.assertRaises(x.RecompError):
                x.project_name(name)

    def test_manifest_case_and_toml_escaping(self):
        root = Path(self.temp.name)
        game = root / ('Game "Data"' if os.name != "nt" else "Game Data")
        exe = game / "Default.XEX"
        make_xex(exe)
        dll = game / "SubDir" / "Engine.DLL"
        dll.parent.mkdir()
        dll.touch()
        project = root / "project"
        project.mkdir()
        manifest = project / "test.toml"
        dll_relative = os.path.relpath(dll, project).replace(os.sep, "/").lower()
        manifest.write_text('[project]\ngame_root="../game"\n[entrypoint]\nfile_path="../game/default.xex"\n[[modules]]\nfile_path=' + json.dumps(dll_relative) + '\n')
        x.fix_manifest_paths(manifest, exe, game)
        import tomllib
        m = tomllib.loads(manifest.read_text())
        self.assertEqual(m["project"]["game_root"], game.as_posix())
        self.assertEqual(m["entrypoint"]["file_path"], exe.as_posix())
        self.assertEqual(m["modules"][0]["file_path"], dll.as_posix())

    def test_nonzero_child_is_failure_and_logged(self):
        import sys
        log = Path(self.temp.name) / "build.log"
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(x.RecompError):
            x.run([sys.executable, "-c", "print('diagnostic'); raise SystemExit(7)"],
                  Path(self.temp.name), log)
        self.assertIn("diagnostic", log.read_text())


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = {"schema": 1, "name": "test", "sdk_version": x.SDK_VERSION,
                      "sdk": str(self.root / "sdk"), "manifest": "test_manifest.toml",
                      "status": "built", "executable": "/stale/executable"}
        (self.root / "test_manifest.toml").touch()
        x.write_json(self.root / x.PROJECT_FILE, self.state)

    def test_manifest_cannot_escape_project(self):
        self.state["manifest"] = "../outside.toml"
        x.write_json(self.root / x.PROJECT_FILE, self.state)
        with self.assertRaises(x.RecompError):
            x.load_project(self.root)

    def test_failed_codegen_invalidates_old_executable(self):
        with patch.object(x, "check_sdk", return_value=Path("rexglue")), \
             patch.object(x, "run", side_effect=x.RecompError("analysis failure")), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(x.RecompError):
                x.codegen(self.root)
        state = x.load_project(self.root)
        self.assertEqual(state["status"], "codegen_failed")
        self.assertIsNone(state["executable"])

    def test_run_refuses_unbuilt_project(self):
        self.state["status"] = "generated"
        x.write_json(self.root / x.PROJECT_FILE, self.state)
        with self.assertRaises(x.RecompError):
            x.launch(self.root)

    def test_sdk_version_mismatch_is_reported(self):
        exe = x.sdk_executable(self.root)
        exe.parent.mkdir()
        exe.touch()
        with patch.object(subprocess, "check_output", return_value="0.9.0"):
            with self.assertRaisesRegex(x.RecompError, "Expected ReXGlue"):
                x.check_sdk(self.root)


@unittest.skipUnless(os.environ.get("XBO360_TEST_SDK"), "Set XBO360_TEST_SDK for official SDK integration")
class SDKIntegrationTests(unittest.TestCase):
    def test_real_codegen_translates_original_ppc_fixture(self):
        from ci.make_test_xex import make_test_xex
        with tempfile.TemporaryDirectory(prefix="xbo360-codegen-") as tmp:
            root = Path(tmp)
            exe = root / "Game Data" / "Default.xex"
            make_test_xex(exe)
            project = root / "Project"
            sdk = Path(os.environ["XBO360_TEST_SDK"])
            with contextlib.redirect_stdout(io.StringIO()):
                x.prepare(exe, project, "fixture", sdk, exe.parent)
                x.codegen(project)
            self.assertEqual(x.load_project(project)["status"], "generated")
            self.assertTrue((project / "generated/default/sources.cmake").is_file())
            sources = "\n".join(p.read_text() for p in project.rglob("*.cpp"))
            self.assertIn("82001000", sources)

    def test_real_init_preserves_paths_and_stages_xenos(self):
        with tempfile.TemporaryDirectory(prefix="xbo360-test-") as tmp:
            root = Path(tmp)
            game = root / "Game Data"
            exe = game / "Default.XEX"
            make_xex(exe)
            project = root / "Project"
            with contextlib.redirect_stdout(io.StringIO()):
                state = x.prepare(exe, project, "smoke", Path(os.environ["XBO360_TEST_SDK"]), game)
            self.assertEqual(state["status"], "prepared")
            self.assertIn("GPU_PLUGINS xenos", (project / "CMakeLists.txt").read_text())
            header = (project / "src/smoke_app.h").read_text()
            self.assertIn('game:\\\\Default.XEX', header)
            self.assertIn('REXCVAR_GET(xbo_renderer)', header)
            import tomllib
            m = tomllib.loads((project / state["manifest"]).read_text())
            self.assertEqual(Path(m["entrypoint"]["file_path"]).resolve(), exe.resolve())
            # Synthetic header is intentionally not a runnable XEX: SDK must fail cleanly.
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(x.RecompError):
                x.codegen(project)
            self.assertEqual(x.load_project(project)["status"], "codegen_failed")


if __name__ == "__main__":
    unittest.main()
