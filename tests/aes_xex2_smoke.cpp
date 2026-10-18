// Synthetic AES/XEX2 round-trip and NIST known-answer tests.
// No copyrighted game data. Covers real XEX2 retail key unwrap + CBC.
#include "../native/include/loader/aes128.h"
#include "../native/include/loader/xex_loader.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {
constexpr std::array<uint8_t,16> retailKey{{
    0x20,0xb1,0x85,0xa5,0x9d,0x28,0xfd,0xc3,
    0x40,0x58,0x3f,0xbb,0x08,0x96,0xbf,0x91
}};

void be16(std::vector<uint8_t>& data, size_t pos, uint16_t n) {
    data.at(pos) = uint8_t(n >> 8); data.at(pos+1) = uint8_t(n);
}
void be32(std::vector<uint8_t>& data, size_t pos, uint32_t n) {
    for (size_t i=0; i<4; ++i) data.at(pos+i) = uint8_t(n >> (24-i*8));
}
void writeFile(const std::filesystem::path& path,
               const std::vector<uint8_t>& data) {
    std::ofstream f(path, std::ios::binary | std::ios::trunc);
    assert(f);
    f.write(reinterpret_cast<const char*>(data.data()),
            static_cast<std::streamsize>(data.size()));
    assert(f.good());
}
std::vector<uint8_t> xexEncrypted(uint16_t compression, bool validKey) {
    constexpr size_t headerSize = 0x300;
    std::vector<uint8_t> b(headerSize + 16, 0);
    be32(b, 0, 0x58455832);
    be32(b, 8, headerSize);
    be32(b, 0x10, 0x100); // security
    be32(b, 0x14, 3); // three optional headers
    be32(b, 0x18, 0x00010100); be32(b, 0x1c, 0x82000000);
    be32(b, 0x20, 0x00040006); be32(b, 0x24, 0xc0);
    be32(b, 0x28, 0x000003ff); be32(b, 0x2c, 0x80);
    be32(b, 0x80, compression == 1 ? 16 : 8);
    be16(b, 0x84, 1); be16(b, 0x86, compression);
    if (compression == 1) {
        be32(b, 0x88, 16); be32(b, 0x8c, 16); // 16 decrypted + 16 zeroes
    }
    be32(b, 0xcc, 0x58455821); // synthetic title ID XEX!
    be32(b, 0x104, 0x2000);
    be32(b, 0x210, 0x82000000);
    constexpr std::array<uint8_t,16> session{{
        0x00,0x11,0x22,0x33,0x44,0x55,0x66,0x77,
        0x88,0x99,0xaa,0xbb,0xcc,0xdd,0xee,0xff
    }};
    // XEX2 security header AES seed at security+0x150 == 0x250.
    x360::Aes128::ecbEncrypt(retailKey.data(), session.data(), b.data()+0x250);
    if (!validKey) b[0x250] ^= 0x80;

    const uint8_t plain[16] = {
        'M','Z',0x90,0,0,0,0,0,0,0,0,0,0,0,0,0
    };
    std::copy(plain, plain+16, b.begin()+headerSize);
    uint8_t iv[16]{};
    x360::Aes128::cbcEncrypt(session.data(), iv, b.data()+headerSize, 16);
    return b;
}
}

int main() {
    // FIPS-197 Appendix B: AES-128 ECB known answer (not a round-trip-only test).
    constexpr std::array<uint8_t,16> key{{
        0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,
        0x08,0x09,0x0a,0x0b,0x0c,0x0d,0x0e,0x0f
    }};
    constexpr std::array<uint8_t,16> plain{{
        0x00,0x11,0x22,0x33,0x44,0x55,0x66,0x77,
        0x88,0x99,0xaa,0xbb,0xcc,0xdd,0xee,0xff
    }};
    constexpr std::array<uint8_t,16> cipher{{
        0x69,0xc4,0xe0,0xd8,0x6a,0x7b,0x04,0x30,
        0xd8,0xcd,0xb7,0x80,0x70,0xb4,0xc5,0x5a
    }};
    std::array<uint8_t,16> out{};
    x360::Aes128::ecbEncrypt(key.data(), plain.data(), out.data());
    assert(out == cipher);
    x360::Aes128::ecbDecrypt(key.data(), cipher.data(), out.data());
    assert(out == plain);

    // NIST SP 800-38A F.2.1 AES128 CBC known-answer test.
    constexpr uint8_t cbcKey[16] = {
        0x2b,0x7e,0x15,0x16,0x28,0xae,0xd2,0xa6,
        0xab,0xf7,0x15,0x88,0x09,0xcf,0x4f,0x3c
    };
    constexpr std::array<uint8_t,16> cbcPlain{{
        0x6b,0xc1,0xbe,0xe2,0x2e,0x40,0x9f,0x96,
        0xe9,0x3d,0x7e,0x11,0x73,0x93,0x17,0x2a
    }};
    constexpr std::array<uint8_t,16> cbcCipher{{
        0x76,0x49,0xab,0xac,0x81,0x19,0xb2,0x46,
        0xce,0xe9,0x8e,0x9b,0x12,0xe9,0x19,0x7d
    }};
    uint8_t iv[16] = {
        0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,
        0x08,0x09,0x0a,0x0b,0x0c,0x0d,0x0e,0x0f
    };
    out = cbcPlain;
    x360::Aes128::cbcEncrypt(cbcKey, iv, out.data(), out.size());
    assert(out == cbcCipher);
    for (unsigned i=0; i<16; ++i) iv[i] = uint8_t(i);
    x360::Aes128::cbcDecrypt(cbcKey, iv, out.data(), out.size());
    assert(out == cbcPlain);

    const auto dir = std::filesystem::temp_directory_path() /
                     "xbox360recomp_crypto_xex_fixture";
    std::filesystem::create_directories(dir);
    const auto file = dir / "synthetic.xex";
    x360::XexLoader reader;
    x360::XexImage image{};

    // Actual header unwrap + ciphertext (16 bytes) -> MZ image.
    writeFile(file, xexEncrypted(0, true));
    assert(reader.load(file.string(), image));
    assert(image.titleId == "58455821");
    assert(image.rawMemory.size() == 16);
    assert(image.rawMemory[0] == 'M' && image.rawMemory[1] == 'Z');

    // BASIC block zero-fill after successful decryption.
    writeFile(file, xexEncrypted(1, true));
    assert(reader.load(file.string(), image));
    assert(image.rawMemory.size() == 32);
    assert(image.rawMemory[16] == 0);

    // Wrong key should not produce an executable.
    writeFile(file, xexEncrypted(0, false));
    assert(!reader.load(file.string(), image));
    assert(reader.lastError().find("MZ") != std::string::npos);

    // LZX is deliberately still unsupported after AES, never false success.
    writeFile(file, xexEncrypted(2, true));
    assert(!reader.load(file.string(), image));
    assert(reader.lastError().find("LZX") != std::string::npos);
    assert(reader.lastError().find("AES stage") != std::string::npos);

    // Strict 16-byte block alignment for encrypted payload.
    auto invalid = xexEncrypted(0, true);
    invalid.push_back(0);
    writeFile(file, invalid);
    assert(!reader.load(file.string(), image));
    assert(reader.lastError().find("block size") != std::string::npos);

    std::filesystem::remove_all(dir);
    std::cout << "AES ECB, CBC, retail XEX2 key unwrap, encrypted BASIC, "
                 "and LZX-not-ready validation passed\n";
}
