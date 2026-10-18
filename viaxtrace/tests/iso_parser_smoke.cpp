#include "../native/include/loader/iso_parser.h"

#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <string>
#include <vector>

namespace {
void le16(std::vector<uint8_t>& v, size_t p, uint16_t n) {
    v[p]=static_cast<uint8_t>(n);
    v[p+1]=static_cast<uint8_t>(n>>8);
}
void le32(std::vector<uint8_t>& v, size_t p, uint32_t n) {
    for(int i=0;i<4;++i) v[p+i]=static_cast<uint8_t>(n>>(i*8));
}
void fixture(const std::filesystem::path& path,uint64_t base,bool truncate=false) {
    constexpr uint64_t kSector=2048;
    constexpr char magic[]="MICROSOFT*XBOX*MEDIA";
    std::vector<uint8_t> header(2048,0);
    std::copy(magic,magic+20,header.begin());
    std::copy(magic,magic+20,header.begin()+2028);
    le32(header,20,33);
    le32(header,24,25);
    std::vector<uint8_t> tree(25,0);
    le16(tree,0,0);
    le16(tree,2,0);
    le32(tree,4,34);
    le32(tree,8,16);
    tree[12]=0x20;
    tree[13]=11;
    std::copy_n("default.xex",11,tree.begin()+14);
    std::array<uint8_t,16> xex={'X','E','X','2','S','Y','N','T','H','E','T','I','C','0','0','1'};
    FILE* f=std::fopen(path.string().c_str(),"wb+");
    assert(f);
    auto write=[&](uint64_t at,const void* data,size_t len) {
        assert(fseeko(f,static_cast<off_t>(at),SEEK_SET)==0);
        assert(std::fwrite(data,1,len,f)==len);
    };
    write(base+32*kSector,header.data(),header.size());
    write(base+33*kSector,tree.data(),tree.size());
    write(base+34*kSector,xex.data(),xex.size());
    if (truncate) {
        assert(ftruncate(fileno(f),static_cast<off_t>(base+34*kSector+12))==0);
    }
    std::fclose(f);
}
}
int main() {
    const auto root=std::filesystem::temp_directory_path()/"x360_viax_iso_smoke";
    std::filesystem::create_directories(root);
    for (auto partition : {uint64_t(0),uint64_t(34078720)}) {
        auto file=root/(std::to_string(partition)+".iso");
        fixture(file,partition);
        x360::IsoParser iso;
        assert(iso.open(file.string()));
        auto entries=iso.listFiles();
        assert(entries.size()==1);
        assert(entries[0].name=="default.xex");
        assert(entries[0].offset==partition+34*2048);
        auto destination=root/(std::to_string(partition)+".xex");
        assert(iso.extractFile(entries[0],destination.string()));
        assert(std::filesystem::file_size(destination)==16);
    }
    auto invalid=root/"truncated.iso";
    fixture(invalid,0,true);
    x360::IsoParser bad;
    assert(!bad.open(invalid.string()));
    std::filesystem::remove_all(root);
    std::puts("ViaXTrace ISO reader: XISO/XGD3/truncation fixtures passed");
}
