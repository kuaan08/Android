#include "../native/include/loader/xex_loader.h"

#include <cassert>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {
void be16(std::vector<uint8_t>& b, size_t at, uint16_t v) {
    b.at(at) = uint8_t(v >> 8);
    b.at(at + 1) = uint8_t(v);
}
void be32(std::vector<uint8_t>& b, size_t at, uint32_t v) {
    for (int i = 0; i < 4; ++i) b.at(at + i) = uint8_t(v >> (24 - i*8));
}
void write(const std::filesystem::path& path, const std::vector<uint8_t>& data) {
    std::ofstream f(path, std::ios::binary);
    assert(f);
    f.write(reinterpret_cast<const char*>(data.data()), data.size());
    assert(f.good());
}
std::vector<uint8_t> xex(uint16_t encryption, uint16_t compression) {
    constexpr size_t h = 0x300;
    auto b = std::vector<uint8_t>(h+8, 0);
    be32(b, 0, 0x58455832);    // XEX2
    be32(b, 8, h);             // size of headers / start of PE payload
    be32(b, 0x10, 0x100);      // XEX2 security header offset
    be32(b, 0x14, 3);          // entry, execution-info, file-format
    be32(b, 0x18, 0x00010100); be32(b, 0x1c, 0x82000000);
    be32(b, 0x20, 0x00040006); be32(b, 0x24, 0xc0);
    be32(b, 0x28, 0x000003ff); be32(b, 0x2c, 0x80);
    be32(b, 0x80, compression == 1 ? 16 : 8);
    be16(b, 0x84, encryption);
    be16(b, 0x86, compression);
    if (compression == 1) { be32(b, 0x88, 6); be32(b, 0x8c, 2); }
    be32(b, 0xcc, 0x12345678);  // execution_info.title_id
    be32(b, 0x104, 0x1000);     // security.image_size
    be32(b, 0x210, 0x82000000);// security.load_address (offset 0x110)
    b[h] = 'M'; b[h+1] = 'Z'; b[h+2] = 0x90;
    return b;
}
}

int main() {
    const auto root = std::filesystem::temp_directory_path() /
                      "xbox360recomp_xex2_synthetic_smoke";
    std::filesystem::create_directories(root);
    const auto file = root / "default.xex";
    x360::XexLoader loader;
    x360::XexImage image{};

    write(file, xex(0,0));
    assert(loader.load(file.string(), image));
    assert(image.titleId == "12345678");
    assert(image.baseAddress == 0x82000000);
    assert(image.entryPoint == 0x82000000);
    assert(image.rawMemory.size() == 8);
    assert(image.rawMemory[0] == 'M' && image.rawMemory[1] == 'Z');

    auto basic = xex(0,1);
    write(file, basic);
    assert(loader.load(file.string(), image));
    assert(image.rawMemory.size() == 8); // six data + two zero bytes
    assert(image.rawMemory[6] == 0 && image.rawMemory[7] == 0);

    write(file, xex(1,0));
    assert(!loader.load(file.string(), image));
    assert(loader.lastError().find("AES block size") != std::string::npos);

    write(file, xex(0,2));
    assert(!loader.load(file.string(), image));
    assert(loader.lastError().find("LZX") != std::string::npos);

    auto bad = xex(0,0);
    be32(bad, 0x24, 0xfffffff0); // execution info outside image
    write(file, bad);
    assert(!loader.load(file.string(), image));
    assert(loader.lastError().find("execution info") != std::string::npos);

    bad = xex(0,0);
    be32(bad, 0x210, 0x0);       // load address incorrect
    be32(bad, 0x1c, 0x82000000);
    write(file, bad);
    assert(!loader.load(file.string(), image));

    bad = xex(0,1);
    be32(bad, 0x88, 0xffffffff); // truncated BASIC block
    write(file, bad);
    assert(!loader.load(file.string(), image));
    assert(loader.lastError().find("BASIC") != std::string::npos);

    bad = xex(0,0);
    be32(bad, 0x14, 0xffffffff); // unbounded directory
    write(file, bad);
    assert(!loader.load(file.string(), image));

    std::filesystem::remove_all(root);
    std::cout << "XEX2 synthetic fixtures pass: valid header, basic compression, "
                 "unsupported encryption/LZX, malformed offsets and lengths\n";
}
