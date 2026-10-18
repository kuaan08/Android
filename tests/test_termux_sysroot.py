"""Offline tests for official NDK metadata selection and safe sysroot extraction."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("termux_ndk_sysroot", ROOT / "termux/fetch_ndk_sysroot.py")
NDK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NDK)


class TermuxSysrootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_selects_linux_archive_and_metadata_sha1(self):
        xml = ET.fromstring("""<repository>
          <remotePackage path="ndk;27.2.12479018"><archives>
            <archive><host-os>windows</host-os><complete><url>wrong.zip</url>
              <checksum type="sha1">bad</checksum></complete></archive>
            <archive><host-os>linux</host-os><complete>
              <url>android-ndk-r27c-linux.zip</url><checksum type="sha1">0123456789abcdef0123456789abcdef01234567</checksum>
            </complete></archive>
          </archives></remotePackage>
        </repository>""")
        url, digest = NDK.select_archive(xml)
        self.assertTrue(url.startswith(NDK.URL_PREFIX))
        self.assertEqual(digest, "0123456789abcdef0123456789abcdef01234567")

    def test_extracts_only_sysroot_members(self):
        archive = self.root / "ndk.zip"
        prefix = NDK.SYSROOT_MEMBER_PREFIX
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr(prefix + "usr/include/c++/v1/string", "header")
            z.writestr(prefix + "usr/lib/aarch64-linux-android/libc++_shared.so", "libc++")
            z.writestr(prefix + "usr/lib/aarch64-linux-android/33/libvulkan.so", "vulkan")
            z.writestr("android-ndk-r27c/toolchains/llvm/prebuilt/linux-x86_64/bin/clang", "do not extract")
        sysroot = NDK.extract_sysroot(archive, self.root / "out")
        self.assertEqual(sysroot, (self.root / "out/sysroot").resolve())
        self.assertEqual((sysroot / "usr/include/c++/v1/string").read_text(), "header")
        self.assertFalse((self.root / "out/bin/clang").exists())

    def test_rejects_parent_traversal_in_zip_member(self):
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr(NDK.SYSROOT_MEMBER_PREFIX + "../escape", "bad")
        with self.assertRaisesRegex(ValueError, "Unsafe path"):
            NDK.extract_sysroot(archive, self.root / "out")

    def test_requires_core_api33_vulkan_and_libcxx(self):
        archive = self.root / "incomplete.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr(NDK.SYSROOT_MEMBER_PREFIX + "usr/include/c++/v1/string", "header")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            NDK.extract_sysroot(archive, self.root / "out")


if __name__ == "__main__":
    unittest.main()
