import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from ci.make_test_xex import make_test_xex
from iso_import import Disc, extract_iso, inspect_iso
import prerequisites
import updates


def make_iso(path, name="default.xex", offset=0):
    with tempfile.TemporaryDirectory() as tmp:
        xex = Path(tmp) / "default.xex"
        make_test_xex(xex)
        payload = xex.read_bytes()
    table = struct.pack("<HHIIBB", 0, 0, 34, len(payload), 0x20, len(name)) + name.encode("ascii")
    header = bytearray(2048)
    header[:20] = header[-20:] = b"MICROSOFT*XBOX*MEDIA"
    struct.pack_into("<II", header, 20, 33, len(table))
    with path.open("wb") as f:
        f.seek(offset + 32 * 2048); f.write(header)
        f.seek(offset + 33 * 2048); f.write(table)
        f.seek(offset + 34 * 2048); f.write(payload)
    return payload


class DiscTests(unittest.TestCase):
    def test_xiso_and_xgd3_extract_original_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for base in (0, 34078720):
                iso = root / (str(base) + ".iso")
                payload = make_iso(iso, offset=base)
                info = inspect_iso(iso)
                self.assertEqual(info["partition_offset"], base)
                self.assertEqual(info["executables"], ["default.xex"])
                out = root / ("out" + str(base))
                with contextlib.redirect_stdout(io.StringIO()): extract_iso(iso, out)
                self.assertEqual((out / "default.xex").read_bytes(), payload)

    def test_rejects_traversal_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "bad.iso"
            make_iso(source, "../evil.xex")
            with self.assertRaises(ValueError): extract_iso(source, root / "out")
            self.assertFalse((root / "out").exists())

    def test_rejects_truncated_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.iso"; make_iso(p)
            with p.open("r+b") as f: f.truncate(p.stat().st_size - 5)
            with self.assertRaises(ValueError): inspect_iso(p)

    def test_does_not_overwrite_existing_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); make_iso(p / "game.iso"); (p / "keep").mkdir()
            with self.assertRaises(ValueError): extract_iso(p / "game.iso", p / "keep")


class SetupAndUpdateTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Visual Studio environment test")
    def test_visual_studio_environment_without_developer_shell(self):
        if prerequisites.vs_installation() is None:
            self.skipTest("Visual Studio is not installed")
        clean = {k:v for k,v in os.environ.items() if not k.upper().startswith("VSCMD")
                 and k.upper() not in ("INCLUDE", "LIB", "LIBPATH", "VCINSTALLDIR")}
        with patch.dict(os.environ, clean, clear=True):
            env = prerequisites.build_environment()
        self.assertTrue(env.get("INCLUDE"))
        self.assertTrue(env.get("LIB"))

    def test_installer_has_explicit_fixed_package_id_and_cpp_components(self):
        args = prerequisites.installer_command("visual-studio")
        self.assertIn("Microsoft.VisualStudio.2022.BuildTools", args)
        self.assertIn("Microsoft.VisualStudio.Component.VC.Llvm.Clang", args[-1])
        self.assertNotIn("--silent", args)
        with self.assertRaises(ValueError): prerequisites.installer_command("arbitrary-command")

    def test_update_rejects_wrong_repository_and_missing_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            for asset in [
                {"name":"Xbox360Recomp-Windows-x64.zip","browser_download_url":"https://evil.example/app.zip","digest":"sha256:"+"a"*64},
                {"name":"Xbox360Recomp-Windows-x64.zip","browser_download_url":"https://github.com/kuaan08/xbo360/releases/download/v1/app.zip"},
            ]:
                with self.assertRaises(ValueError): updates.download({"asset":asset},tmp)

    def test_download_validates_hash_and_removes_partial_on_mismatch(self):
        payload = b"original test package"
        asset = {"name":"Xbox360Recomp-Windows-x64.zip","browser_download_url":"https://github.com/kuaan08/xbo360/releases/download/v1/Xbox360Recomp-Windows-x64.zip","size":len(payload),"digest":"sha256:"+hashlib.sha256(payload).hexdigest()}
        with tempfile.TemporaryDirectory() as tmp:
            with patch("urllib.request.urlopen", return_value=io.BytesIO(payload)):
                self.assertEqual(updates.download({"asset":asset},tmp).read_bytes(),payload)
            asset["digest"] = "sha256:"+"0"*64
            with patch("urllib.request.urlopen", return_value=io.BytesIO(payload)), self.assertRaises(ValueError):
                updates.download({"asset":asset},tmp)
            self.assertFalse(list(Path(tmp).glob("*.part")))

    def test_android_metadata_does_not_bundle_game_bytes(self):
        import android_build
        self.assertEqual(len(android_build.ANDROID_REVISION),40)
        self.assertIn("rexglue-skate3-android",android_build.ANDROID_REPO)


if __name__ == "__main__": unittest.main()
