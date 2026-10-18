/** Bounded Xbox XDVDFS/XISO and ISO9660 reader for Android and host CI. */
#include "../../include/loader/iso_parser.h"
#include <algorithm>
#include <array>
#include <cctype>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <vector>

#ifdef __ANDROID__
#include <android/log.h>
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,"X360:ISO",__VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"X360:ISO",__VA_ARGS__)
#else
#include <cstdio>
#define LOGI(...) do {} while (0)
#define LOGE(...) do {} while (0)
#endif

namespace x360 {
namespace {
constexpr uint64_t sectorSize = 2048;
constexpr char magic[] = "MICROSOFT*XBOX*MEDIA";
constexpr size_t maxFiles = 200000;

uint16_t le16(const uint8_t* p) {
    return static_cast<uint16_t>(p[0]) | (static_cast<uint16_t>(p[1]) << 8);
}
uint32_t le32(const uint8_t* p) {
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}
bool seek(FILE* f, uint64_t offset) {
    if (offset > static_cast<uint64_t>(INT64_MAX)) return false;
    return fseeko(f, static_cast<off_t>(offset), SEEK_SET) == 0;
}
bool readAt(FILE* f, uint64_t offset, void* out, size_t count, uint64_t fileSize) {
    return offset <= fileSize && count <= fileSize - offset && seek(f, offset) &&
           fread(out, 1, count, f) == count;
}
bool safeName(const std::string& name) {
    if (name.empty() || name == "." || name == "..") return false;
    for (unsigned char ch : name) {
        if (ch < 32 || ch == '/' || ch == '\\' || ch == ':') return false;
    }
    return true;
}
std::string lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
}
} // namespace

IsoParser::IsoParser() = default;
IsoParser::~IsoParser() { close(); }

void IsoParser::close() {
    if (m_file) fclose(m_file);
    m_file = nullptr;
    m_path.clear();
    m_files.clear();
    m_seenDirectories.clear();
    m_fileSize = 0;
    m_partitionOffset = 0;
    m_isXdvdfs = false;
    m_lastError.clear();
}

bool IsoParser::open(const std::string& path) {
    close();
    m_file = fopen(path.c_str(), "rb");
    if (!m_file) { m_lastError = "Cannot open ISO"; return false; }
    m_path = path;
    if (fseeko(m_file, 0, SEEK_END) != 0) {
        m_lastError = "Cannot seek ISO";
        return false;
    }
    const off_t size = ftello(m_file);
    if (size < 0) { m_lastError = "Cannot determine ISO size"; return false; }
    m_fileSize = static_cast<uint64_t>(size);

    for (uint64_t base : {0ULL, 34078720ULL, 265879552ULL, 405798912ULL}) {
        std::array<uint8_t,2048> header{};
        if (!readAt(m_file, base + 32 * sectorSize, header.data(),
                    header.size(), m_fileSize)) continue;
        if (std::memcmp(header.data(), magic, 20) == 0 &&
            std::memcmp(header.data()+2028, magic, 20) == 0) {
            m_partitionOffset = base;
            m_isXdvdfs = true;
            if (parseXdvdfs()) return true;
            m_lastError = "XDVDFS volume is malformed or contains no files";
            return false;
        }
    }
    m_isXdvdfs = false;
    if (parseIso9660()) return true;
    if (m_lastError.empty()) m_lastError = "Not a supported ISO9660 or Xbox XDVDFS image";
    return false;
}

bool IsoParser::parseXdvdfs() {
    std::array<uint8_t,2048> header{};
    if (!readAt(m_file, m_partitionOffset + 32 * sectorSize, header.data(),
                header.size(), m_fileSize)) return false;
    const uint32_t rootSector = le32(header.data() + 20);
    const uint32_t rootSize = le32(header.data() + 24);
    if (!rootSize || rootSize > 64U * 1024 * 1024) return false;
    walkXdvdfsDirectory(m_partitionOffset + uint64_t(rootSector)*sectorSize,rootSize,"");
    return !m_files.empty();
}

void IsoParser::walkXdvdfsDirectory(uint64_t offset, uint32_t size,
                                    const std::string& prefix, int depth) {
    if (depth > 64 || m_files.size() >= maxFiles ||
        !size || size > 64U * 1024 * 1024 ||
        !m_seenDirectories.insert(offset).second ||
        offset > m_fileSize || size > m_fileSize - offset) return;
    std::vector<uint8_t> buf(size);
    if (!readAt(m_file, offset, buf.data(), size, m_fileSize)) return;
    std::vector<size_t> pending = {0};
    std::unordered_set<size_t> visited;
    while (!pending.empty() && m_files.size() < maxFiles) {
        const size_t pos = pending.back();
        pending.pop_back();
        if (!visited.insert(pos).second || pos > buf.size() ||
            buf.size() - pos < 14) continue;
        const uint8_t* p = buf.data()+pos;
        const uint16_t left = le16(p), right = le16(p+2);
        const uint32_t sector = le32(p+4), length = le32(p+8);
        const uint8_t attributes = p[12], nameLength = p[13];
        if (!nameLength || nameLength > buf.size()-pos-14) continue;
        const std::string name(reinterpret_cast<const char*>(p+14),nameLength);
        if (!safeName(name)) continue;
        const std::string fullPath = prefix.empty() ? name : (prefix+"/"+name);
        const uint64_t fileOffset = m_partitionOffset+uint64_t(sector)*sectorSize;
        if (fileOffset <= m_fileSize && length <= m_fileSize - fileOffset) {
            const bool directory = (attributes & 0x10) != 0;
            m_files.push_back({fullPath,fileOffset,length,directory});
            if (directory && length) {
                walkXdvdfsDirectory(fileOffset,length,fullPath,depth+1);
            }
        }
        // Child offsets are 4-byte units from the CURRENT DIRECTORY TABLE,
        // not absolute sector numbers and not relative to the current node.
        if (right && right != 0xffff) pending.push_back(size_t(right)*4);
        if (left && left != 0xffff) pending.push_back(size_t(left)*4);
    }
}

bool IsoParser::parseIso9660() {
    std::array<uint8_t,2048> pvd{};
    if (!readAt(m_file,16*sectorSize,pvd.data(),pvd.size(),m_fileSize) ||
        pvd[0]!=1 || std::memcmp(pvd.data()+1,"CD001",5)!=0) {
        m_lastError = "Missing ISO9660 primary volume descriptor";
        return false;
    }
    if (pvd[156] < 34) return false;
    const uint32_t rootSector=le32(pvd.data()+156+2);
    const uint32_t rootSize=le32(pvd.data()+156+10);
    walkIso9660Directory(rootSector,rootSize,"");
    return !m_files.empty();
}

void IsoParser::walkIso9660Directory(uint32_t sector,uint32_t size,
                                    const std::string& prefix,int depth) {
    const uint64_t offset=uint64_t(sector)*sectorSize;
    if (depth>64 || m_files.size()>=maxFiles || !size ||
        size>64U*1024*1024 || !m_seenDirectories.insert(offset).second ||
        offset>m_fileSize || size>m_fileSize-offset) return;
    std::vector<uint8_t> data(size);
    if (!readAt(m_file,offset,data.data(),data.size(),m_fileSize)) return;
    size_t pos=0;
    while(pos<data.size() && m_files.size()<maxFiles) {
        const uint8_t recLen=data[pos];
        if (!recLen) { pos=((pos/sectorSize)+1)*sectorSize; continue; }
        if (recLen < 34 || recLen>data.size()-pos) break;
        const uint8_t* p=data.data()+pos;
        const uint8_t nameLen=p[32];
        if (nameLen && 33+nameLen<=recLen && !(nameLen==1&&(p[33]==0||p[33]==1))) {
            std::string name(reinterpret_cast<const char*>(p+33),nameLen);
            const size_t semicolon=name.find(';');
            if (semicolon!=std::string::npos) name.resize(semicolon);
            if (safeName(name)) {
                const uint32_t childSector=le32(p+2),length=le32(p+10);
                const uint64_t fileOffset=uint64_t(childSector)*sectorSize;
                const bool directory=(p[25]&2)!=0;
                if (fileOffset<=m_fileSize && length<=m_fileSize-fileOffset) {
                    const std::string fullPath=prefix.empty()?name:prefix+"/"+name;
                    m_files.push_back({fullPath,fileOffset,length,directory});
                    if(directory && length) walkIso9660Directory(childSector,length,fullPath,depth+1);
                }
            }
        }
        pos+=recLen;
    }
}

const IsoFileEntry* IsoParser::findFile(const std::string& name) const {
    const std::string target=lower(name);
    for (const auto& file:m_files) {
        if(lower(file.name)==target) return &file;
    }
    return nullptr;
}

int IsoParser::readFile(const IsoFileEntry& entry,std::vector<uint8_t>& out) {
    if(!m_file || entry.size>256U*1024*1024 ||
       entry.offset>m_fileSize || entry.size>m_fileSize-entry.offset) return -1;
    out.resize(entry.size);
    if(!readAt(m_file,entry.offset,out.data(),out.size(),m_fileSize)) {
        out.clear();return -1;
    }
    return static_cast<int>(out.size());
}

bool IsoParser::extractFile(const IsoFileEntry& entry,const std::string& destination) {
    if(!m_file || entry.isDirectory || entry.offset>m_fileSize ||
       entry.size>m_fileSize-entry.offset) return false;
    std::ofstream output(destination,std::ios::binary|std::ios::trunc);
    if(!output) {m_lastError="Cannot create extraction output";return false;}
    std::array<uint8_t,1024*1024> buffer{};
    uint64_t at=entry.offset,remaining=entry.size;
    while(remaining) {
        const size_t chunk=static_cast<size_t>(std::min<uint64_t>(remaining,buffer.size()));
        if(!readAt(m_file,at,buffer.data(),chunk,m_fileSize)) {
            output.close();
            std::filesystem::remove(destination);
            m_lastError="Truncated ISO payload";return false;
        }
        output.write(reinterpret_cast<const char*>(buffer.data()),chunk);
        if(!output) { m_lastError="Cannot write extracted file";return false; }
        at+=chunk;
        remaining-=chunk;
    }
    return true;
}
} // namespace x360
