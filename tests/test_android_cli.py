"""Guard the CLI-to-export contract for both Android modes.

No Android SDK or NDK is needed; this tests argument routing only.
"""
import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import xbo360


class AndroidCliTests(unittest.TestCase):
    def test_native_export_keeps_runtime_and_jobs_separate(self):
        with patch("android_build.export") as export:
            result = xbo360.main([
                "android", "--project", "prepared", "--sdk-source", "rex-source",
                "--android-sdk", "sdk", "--ndk", "ndk", "--runtime", "--jobs", "3"
            ])
        self.assertEqual(result, 0)
        export.assert_called_once_with(
            project=Path("prepared"), source=Path("rex-source"),
            ndk=Path("ndk"), sdk=Path("sdk"),
            runtime=True, ondevice_codegen=False, jobs=3,
        )

    def test_launcher_defaults_to_no_native_code(self):
        with patch("android_build.export") as export:
            self.assertEqual(xbo360.main(["android"]), 0)
        export.assert_called_once_with(
            project=None, source=None, ndk=None, sdk=None,
            runtime=False, ondevice_codegen=False, jobs=2,
        )

    def test_ondevice_codegen_is_explicit(self):
        with patch("android_build.export") as export:
            self.assertEqual(xbo360.main(["android", "--ondevice-codegen", "--jobs", "4"]), 0)
        export.assert_called_once_with(
            project=None, source=None, ndk=None, sdk=None,
            runtime=False, ondevice_codegen=True, jobs=4,
        )

    def test_modes_cannot_be_combined(self):
        with patch("android_build.export") as export, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                xbo360.main(["android", "--runtime", "--ondevice-codegen"])
        self.assertEqual(error.exception.code, 2)
        export.assert_not_called()


if __name__ == "__main__":
    unittest.main()
