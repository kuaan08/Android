"""Create an original, unencrypted XEX2 fixture containing li r3,1; blr.

No console SDK, game data, signatures, or third-party binary bytes are used.
This is a loader/codegen/link fixture, not a graphics or gameplay test.
"""
from pathlib import Path
import struct


def make_test_xex(destination: Path) -> None:
    header = bytearray(0x400)
    image = bytearray(0x10000)

    def be(offset, *values):
        struct.pack_into(">" + "I" * len(values), header, offset, *values)

    # XEX2 title, unencrypted/uncompressed file format, entrypoint, image base,
    # anonymous execution metadata, and one code-page descriptor.
    be(0, 0x58455832, 1, len(header), 0, 0x100, 4)
    be(24, 0x3FF, 0x80, 0x10100, 0x82001000, 0x10201, 0x82000000, 0x40006, 0x90)
    struct.pack_into(">IHH", header, 0x80, 8, 0, 0)
    be(0x90, 0, 0, 0, 0, 0, 0)
    be(0x100, 0x19C, len(image))
    be(0x210, 0x82000000)
    be(0x280, 1, 0x11)

    # Little-endian PE32 metadata, big-endian PPC instructions and PDATA.
    image[:4] = bytes.fromhex("4d5a9000")
    struct.pack_into("<I", image, 0x3C, 0x80)
    struct.pack_into("<4sHHIIIHH", image, 0x80, b"PE\0\0", 0x1F2, 2, 0, 0, 0, 224, 0x102)
    optional = 0x98
    struct.pack_into("<H", image, optional, 0x10B)
    struct.pack_into("<I", image, optional + 16, 0x1000)
    struct.pack_into("<I", image, optional + 28, 0x82000000)
    struct.pack_into("<II", image, optional + 32, 0x1000, 0x200)
    struct.pack_into("<II", image, optional + 56, len(image), 0x1000)
    struct.pack_into("<H", image, optional + 68, 14)
    struct.pack_into("<I", image, optional + 92, 16)
    struct.pack_into("<II", image, optional + 96 + 3 * 8, 0x2000, 8)
    for offset, name, address, flags in (
        (optional + 224, b".text", 0x1000, 0x60000020),
        (optional + 264, b".pdata", 0x2000, 0x40000040),
    ):
        struct.pack_into("<8sIIIIIIHHI", image, offset, name, 8, address,
                         8, address, 0, 0, 0, 0, flags)
    image[0x1000:0x1008] = bytes.fromhex("386000014e800020")
    # One 2-instruction function, 32-bit flag, no exception handler.
    struct.pack_into(">II", image, 0x2000, 0x82001000, 0x40000200)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(header + image)


if __name__ == "__main__":
    import sys
    make_test_xex(Path(sys.argv[1]))
