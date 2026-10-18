#pragma once
#include "iso_parser.h"
#include <algorithm>
#include <cctype>
#include <optional>
#include <string>
#include <vector>

namespace x360 {

// Return a durable VALUE, not a pointer into IsoParser::listFiles() temporary.
// Root default.xex takes precedence over nested copies.
inline std::optional<IsoFileEntry> selectDefaultXex(
    const std::vector<IsoFileEntry>& files) {
    std::optional<IsoFileEntry> nested;
    for (const auto& file : files) {
        if (file.isDirectory) continue;
        std::string lower = file.name;
        std::transform(lower.begin(), lower.end(), lower.begin(),
            [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
        if (lower == "default.xex") return file;
        if (!nested && lower.size() >= 12 &&
            lower.compare(lower.size() - 12, 12, "/default.xex") == 0) {
            nested = file;
        }
    }
    return nested;
}

} // namespace x360
