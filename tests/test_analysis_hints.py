"""Regression tests for Force and per-title ReXGlue function boundaries."""
import json
import hashlib
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest import mock

import analysis_hints
import xbo360

LOG = (
    "Analyze: found 1 errors\nUnresolvedCall (1):\n"
    "  0x82C21240 from 0x82C22B14: b 0x82C21240 from 0x82C22B14 - target not in any function\n"
)

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "my_game_manifest.toml"
        self.manifest.write_text(
            '[project]\nname = "my_game"\n'
            '[entrypoint]\nfile_path = "game/default.xex"\n'
            'out_directory_path = "generated/default"\nincludes = []\n',
            encoding="utf-8",
        )
        (self.root / "xbo360-project.json").write_text(
            json.dumps({"schema": 1, "sdk_version": xbo360.SDK_VERSION, "name": "my_game", "manifest": self.manifest.name,
                        "sdk": str(self.root), "status": "codegen_failed"}),
            encoding="utf-8",
        )
        (self.root / "build.log").write_text(LOG, encoding="utf-8")

    def test_diagnose_real_log_pattern(self):
        branches = analysis_hints.diagnose(self.root)["unresolved_branches"]
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0]["source"], "0x82C22B14")
        self.assertEqual(branches[0]["target"], "0x82C21240")

    def test_manual_hint_is_rexglue_toml_include_and_idempotent(self):
        analysis_hints.save_hint(self.root, "0x82C21240", 64)
        manifest = tomllib.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["entrypoint"]["includes"], [analysis_hints.HINT_FILE])
        hints = tomllib.loads((self.root / analysis_hints.HINT_FILE).read_text(encoding="utf-8"))
        self.assertEqual(hints["functions"]["0x82C21240"]["size"], 64)
        analysis_hints.save_hint(self.root, "0x82C21240", 64)
        self.assertEqual(self.manifest.read_text().count(analysis_hints.HINT_FILE), 1)

    def test_preserve_existing_include_and_multiple_hints(self):
        self.manifest.write_text(self.manifest.read_text().replace(
            'includes = []', 'includes = ["custom.toml"]'))
        analysis_hints.save_hint(self.root, "0x82C21240", 64)
        analysis_hints.save_hint(self.root, "0x82C21340", 24, parent=0x82C21000)
        manifest = tomllib.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["entrypoint"]["includes"],
                         ["custom.toml", analysis_hints.HINT_FILE])
        hints = tomllib.loads((self.root / analysis_hints.HINT_FILE).read_text(encoding="utf-8"))
        self.assertEqual(hints["functions"]["0x82C21340"]["parent"], 0x82C21000)

    def test_no_automatic_guess_and_reject_invalid(self):
        for address, size in [("0x82C21241", 64), ("0x82C21240", 0),
                              ("0x82C21240", 7), ("BAD", 64)]:
            with self.subTest(address=address, size=size):
                with self.assertRaises(ValueError):
                    analysis_hints.save_hint(self.root, address, size)
        analysis_hints.save_hint(self.root, "0x82C21240", 64)
        with self.assertRaises(ValueError):
            analysis_hints.save_hint(self.root, "0x82C21240", 128)

    def test_exact_xex_hint_suggestion_requires_checksum_and_explicit_save(self):
        xex = self.root / "default.xex"
        xex.write_bytes(b"XEX2" + bytes(range(32)))
        state_file = self.root / "xbo360-project.json"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state["xex"] = str(xex)
        state_file.write_text(json.dumps(state), encoding="utf-8")
        digest = hashlib.sha256(xex.read_bytes()).hexdigest()
        self.assertFalse(analysis_hints.suggest_hints(self.root)["matching_revision"])
        evidence = {"title": "Synthetic test", "hints": [
            {"address": "0x82C21240", "size": 112, "evidence": "synthetic test only"}
        ]}
        with mock.patch.dict(analysis_hints.KNOWN_EXACT_BINARIES, {digest: evidence}):
            report = analysis_hints.suggest_hints(self.root)
            self.assertTrue(report["matching_revision"])
            self.assertEqual(report["hints"][0]["size"], 112)
            # Suggestions must not write a function hint without the user's approval.
            self.assertFalse((self.root / analysis_hints.HINT_FILE).exists())
            xex.write_bytes(b"XEX2" + bytes(range(31)))
            self.assertFalse(analysis_hints.suggest_hints(self.root)["matching_revision"])

    def test_force_is_a_rexglue_global_argument(self):
        captured = []
        with mock.patch.object(xbo360, "check_sdk", return_value=self.root / "rexglue"), \
             mock.patch.object(xbo360, "run", side_effect=lambda args, *rest: captured.append(args)):
            xbo360.codegen(self.root)
            xbo360.codegen(self.root, force=True)
        self.assertEqual(captured[0][1], "codegen")
        self.assertEqual(captured[1][1:3], ["--force", "codegen"])

if __name__ == "__main__":
    unittest.main()
