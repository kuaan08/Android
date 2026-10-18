"""Android APK tool selection tests, including Termux overrides."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("android_build_for_tools_test", ROOT / "android_build.py")
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class AndroidPackageToolTests(unittest.TestCase):
    def test_termux_tool_overrides_do_not_need_linux_build_tools_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sdk = root / "sdk"
            sdk.mkdir()
            jdk_bin = root / "jdk" / "bin"
            jdk_bin.mkdir(parents=True)
            suffix = ".exe" if os.name == "nt" else ""
            jdk_tools = {}
            for name in ("java", "javac", "keytool"):
                path = jdk_bin / (name + suffix)
                path.write_text("fixture")
                jdk_tools[name] = path
            paths = {}
            for name in ("android.jar", "aapt2", "zipalign", "d8.jar", "apksigner.jar"):
                path = root / name
                path.write_text("fixture")
                paths[name] = path
            environment = {
                "JAVA_HOME": str(root / "jdk"),
                "XBO_ANDROID_JAR": str(paths["android.jar"]),
                "XBO_AAPT2": str(paths["aapt2"]),
                "XBO_ZIPALIGN": str(paths["zipalign"]),
                "XBO_D8_JAR": str(paths["d8.jar"]),
                "XBO_APKSIGNER_JAR": str(paths["apksigner.jar"]),
            }
            with patch.dict(os.environ, environment):
                _, tools = BUILD.tools(sdk)
            # Windows can return a long canonical path for an 8.3 temp alias
            # (RUNNER~1 vs runneradmin). Compare file identity, not spelling.
            for name, expected in (("android", paths["android.jar"]),
                                   ("aapt2", paths["aapt2"]),
                                   ("zipalign", paths["zipalign"]),
                                   ("d8", paths["d8.jar"]),
                                   ("apksigner", paths["apksigner.jar"])):
                self.assertTrue(os.path.samefile(tools[name], expected), name)
            for name in ("java", "javac", "keytool"):
                self.assertTrue(os.path.samefile(tools[name], jdk_tools[name]), name)


if __name__ == "__main__":
    unittest.main()
