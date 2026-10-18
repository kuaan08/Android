// Fully synthetic XDVDFS -> default.xex -> XEX2 pipeline smoke tests.
// Contains no commercial game data.
#include "../native/include/loader/iso_parser.h"
#include "../native/include/loader/title_disc.h"
#include "../native/include/loader/xex_loader.h"

#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <vector>

namespace {
void le16(std::vector<uint8_t>& b, size_t at, uint16_t value) {
    b.at(at) = uint8_t(value);
    b.at(at + 1) = uint8_t(value >> 8);
}
void le32(std::vector<uint8_t>& b, size_t at, uint32_t value) {
    for (int i = 0; i < 4; ++i) b.at(at + i) = uint8_t(value >> (i * 8));
}
void be16(std::vector<uint8_t>& b, size_t at, uint16_t value) {
    b.at(at) = uint8_t(value >> 8);
    b.at(at + 1) = uint8_t(value);
}
void be32(std::vector<uint8_t>& b, size_t at, uint32_t value) {
    for (int i = 0; i < 4; ++i) b.at(at + i) = uint8_t(value >> (24 - i * 8));
}
std::vector<uint8_t> syntheticXex(bool invalid) {
    constexpr size_t headerSize = 0x300;
    std::vector<uint8_t> data(headerSize + 8, 0);
    be32(data, 0, invalid ? 0x42414421 : 0x58455832); // BAD! or XEX2
    be32(data, 8, headerSize);
    be32(data, 0x10, 0x100);
    be32(data, 0x14, 3);
    be32(data, 0x18, 0x00010100); be32(data, 0x1c, 0x82000000);
    be32(data, 0x20, 0x00040006); be32(data, 0x24, 0xc0);
    be32(data, 0x28, 0x000003ff); be32(data, 0x2c, 0x80);
    be32(data, 0x80, 8); // format header size
    be16(data, 0x84, 0); be16(data, 0x86, 0); // unencrypted, uncompressed
    be32(data, 0xcc, 0x12345678); // synthetic title ID
    be32(data, 0x104, 0x1000);
    be32(data, 0x210, 0x82000000);
    data[headerSize] = 'M'; data[headerSize+1] = 'Z';
    return data;
}
void disc(const std::filesystem::path& path, bool invalidXex) {
    constexpr uint64_t sector = 2048;
    std::vector<uint8_t> hdr(sector, 0);
    std::memcpy(hdr.data(), "MICROSOFT*XBOX*MEDIA", 20);
    std::memcpy(hdr.data()+2028, "MICROSOFT*XBOX*MEDIA", 20);
    le32(hdr, 20, 33);
    le32(hdr, 24, 25);
    std::vector<uint8_t> entry(25, 0);
    le16(entry, 0, 0); le16(entry, 2, 0);
    le32(entry, 4, 34);
    auto xex = syntheticXex(invalidXex);
    le32(entry, 8, static_cast<uint32_t>(xex.size()));
    entry[12] = 0x20;
    entry[13] = 11;
    std::memcpy(entry.data()+14, "default.xex", 11);
    FILE* file = std::fopen(path.string().c_str(), "wb+");
    assert(file);
    auto put = [&](uint64_t pos, const void* data, size_t n) {
        assert(fseeko(file, static_cast<off_t>(pos), SEEK_SET) == 0);
        assert(std::fwrite(data, 1, n, file) == n);
    };
    put(32*sector, hdr.data(), hdr.size());
    put(33*sector, entry.data(), entry.size());
    put(34*sector, xex.data(), xex.size());
    std::fclose(file);
}
}
int main() {
    using namespace x360;
    const auto tmp = std::filesystem::temp_directory_path() / "x360_pipeline_fixture";
    std::filesystem::create_directories(tmp);
    for (bool broken : {false, true}) {
        const auto path = tmp / (broken ? "bad.iso" : "good.iso");
        disc(path, broken);
        IsoParser iso;
        assert(iso.open(path.string()));
        // The library returns temporary listFiles() vectors. This optional
        // must own its metadata after that temporary is destroyed.
        const auto item = selectDefaultXex(iso.listFiles());
        assert(item && item->name == "default.xex");
        const auto dest = tmp / (broken ? "bad_default.xex" : "good_default.xex");
        assert(iso.extractFile(*item, dest.string()));
        assert(std::filesystem::file_size(dest) == item->size);
        XexLoader loader;
        XexImage image{};
        const bool loaded = loader.load(dest.string(), image);
        assert(loaded != broken);
        if (!broken) assert(image.titleId == "12345678");
        if (broken) assert(loader.lastError().find("XEX2") != std::string::npos);
    }
    // Reject names that just contain "default.xex" as a substring.
    std::vector<IsoFileEntry> decoys = {
        {"not-default.xex.backup", 1, 99, false},
        {"sub/Default.XEX", 5, 99, false},
        {"default.xex", 9, 99, false},
    };
    auto preferred = selectDefaultXex(decoys);
    assert(preferred && preferred->offset == 9);
    decoys.clear();
    assert(preferred && preferred->name == "default.xex");
    std::filesystem::remove_all(tmp);
    std::cout << "ISO -> XEX2 integrated pipeline and lifetime regression tests passed\n";
}
