"""Termux builder contract tests; fixtures contain no commercial game data."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("termux_build_generated", ROOT / "termux/build_generated.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class TermuxBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle = self.root / "bundle"
        self.project = self.bundle / "generated-project"
        self.project.mkdir(parents=True)
        self.game_root = self.bundle / "game"
        self.game_root.mkdir()
        self.xex_rel = "Content/Default.XEX"
        self.xex = self.game_root / self.xex_rel
        self.xex.parent.mkdir(parents=True)
        self.xex.write_bytes(b"XEX2" + bytes(40))
        self.name = "game_fixture"
        self.manifest_path = self.project / f"{self.name}_manifest.toml"
        self.manifest_path.write_text(
            '[project]\nname = "game_fixture"\ngame_root = "../game"\n'
            '[entrypoint]\nfile_path = "../game/Content/Default.XEX"\n'
            'out_directory_path = "generated/default"\nincludes = []\n',
            encoding="utf-8")
        entry = self.project / "generated/default"
        entry.mkdir(parents=True)
        (entry / "sources.cmake").write_text("set(GENERATED_SOURCES fixture.cpp)\n", encoding="utf-8")
        (entry / "fixture.cpp").write_text("int fixture() { return 1; }\n", encoding="utf-8")
        (self.project / "src").mkdir()
        (self.project / "src/game_fixture_app.h").write_text(
            "#pragma once\nclass FixtureApp {\n"
            "  auto make() { return PPCImageConfig; }\n"
            "  // void OnLoadXexImage(std::string& xex_image) override {}\n};\n",
            encoding="utf-8")
        (self.project / "src/main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
        self.digest = hashlib.sha256(self.xex.read_bytes()).hexdigest()
        (self.bundle / "xbo-game.json").write_text(json.dumps({
            "title": "Synthetic fixture", "sha256": self.digest, "xex_path": self.xex_rel
        }), encoding="utf-8")

    def test_loads_portable_bundle_and_verifies_xex_hash(self):
        values = BUILDER.load_inputs(self.bundle, self.game_root)
        self.assertEqual(values[5], self.name)
        self.assertEqual(values[7], self.xex.resolve())
        self.assertEqual(values[8], self.xex_rel)

    def test_rejects_xex_path_traversal_and_hash_mismatch(self):
        metadata_path = self.bundle / "xbo-game.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["xex_path"] = "../outside.xex"
        metadata_path.write_text(json.dumps(metadata))
        with self.assertRaises(BUILDER.BuildError):
            BUILDER.load_inputs(self.bundle, self.game_root)
        metadata["xex_path"] = self.xex_rel
        metadata["sha256"] = "0" * 64
        metadata_path.write_text(json.dumps(metadata))
        with self.assertRaises(BUILDER.BuildError):
            BUILDER.load_inputs(self.bundle, self.game_root)

    def test_rejects_guest_dll_until_module_support_exists(self):
        (self.game_root / "Engine.DLL").write_bytes(b"fixture")
        with self.assertRaisesRegex(BUILDER.BuildError, "single-XEX"):
            BUILDER.load_inputs(self.bundle, self.game_root)

    def test_prepares_android_cmake_and_relocates_manifest(self):
        values = BUILDER.load_inputs(self.bundle, self.game_root)
        _, game_root, project, manifest_path, manifest, name, entry, xex, rel, _ = values
        BUILDER.prepare_project(project, manifest_path, manifest, name, entry, game_root, xex, rel)
        cmake = (project / "CMakeLists.txt").read_text(encoding="utf-8")
        header = (project / "src/game_fixture_app.h").read_text(encoding="utf-8")
        parsed = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("set(ANDROID TRUE)", cmake)
        self.assertIn("REXGLUE_USE_VULKAN ON", cmake)
        self.assertIn("-z,max-page-size=16384", cmake)
        self.assertIn("game_fixture_PPCImageConfig", header)
        self.assertIn('xex_image = "game:\\\\Content\\\\Default.XEX";', header)
        self.assertEqual(parsed["project"]["game_root"], game_root.as_posix())
        self.assertEqual(parsed["entrypoint"]["file_path"], xex.as_posix())
        # Re-running is safe and updates the XEX hook without duplicating its method.
        BUILDER.prepare_project(project, manifest_path, parsed, name, entry, game_root, xex, rel)
        self.assertEqual((project / "src/game_fixture_app.h").read_text().count("void OnLoadXexImage"), 1)

    def test_cpp_string_escapes_utf8_and_quotes(self):
        result = BUILDER.cpp_string('game:\\a"é.xex')
        self.assertTrue(result.startswith('"') and result.endswith('"'))
        self.assertIn('\\\\', result)
        self.assertIn('\\"', result)
        self.assertIn('\\303\\251', result)


if __name__ == "__main__":
    unittest.main()
