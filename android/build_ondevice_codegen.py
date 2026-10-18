#!/usr/bin/env python3
"""Build the optional Android launcher APK with on-device ReXGlue codegen."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import android_build  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", help="Android SDK directory; otherwise use project defaults")
    parser.add_argument("--ndk", help="Android NDK directory (r27c / 27.2.12479018)")
    parser.add_argument("--source", help="Existing checkout of the pinned ReXGlue source")
    parser.add_argument("--jobs", type=int, default=2, help="Parallel native build jobs (default: 2)")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")

    apk = android_build.export(
        source=Path(args.source).resolve() if args.source else None,
        ndk=Path(args.ndk).resolve() if args.ndk else None,
        sdk=Path(args.sdk).resolve() if args.sdk else None,
        ondevice_codegen=True,
        jobs=args.jobs,
    )
    print(f"APK: {apk}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
