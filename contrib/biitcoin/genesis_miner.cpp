// Distributed under the MIT software license; see COPYING.
// Optional standalone tool. Requires OpenSSL headers and libcrypto.
#include <openssl/sha.h>

#include <array>
#include <charconv>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

using Header = std::array<unsigned char, 80>;
using Hash = std::array<unsigned char, 32>;

static std::string DisplayHash(const Hash& hash)
{
    static constexpr char HEX[] = "0123456789abcdef";
    std::string result;
    for (auto it = hash.rbegin(); it != hash.rend(); ++it) {
        result += HEX[*it >> 4];
        result += HEX[*it & 15];
    }
    return result;
}

static Hash DoubleHash(const SHA256_CTX& prefix, const Header& header)
{
    SHA256_CTX first = prefix;
    Hash intermediate{}, result{};
    SHA256_Update(&first, header.data() + 64, 16);
    SHA256_Final(intermediate.data(), &first);
    SHA256_CTX second;
    SHA256_Init(&second);
    SHA256_Update(&second, intermediate.data(), intermediate.size());
    SHA256_Final(result.data(), &second);
    return result;
}

static bool MeetsTarget(const Hash& hash)
{
    // Little-endian target encoded by compact nBits 0x1d00ffff.
    Hash target{};
    target[26] = 0xff;
    target[27] = 0xff;
    for (int i = 31; i >= 0; --i) {
        if (hash[i] < target[i]) return true;
        if (hash[i] > target[i]) return false;
    }
    return true;
}

int main(int argc, char** argv)
try {
    if (argc != 2) throw std::runtime_error("Usage: genesis-miner CHECKPOINT_FILE | --self-test");
    Header header{};
    const std::string hex{
        "010000000000000000000000000000000000000000000000000000000000000000000000"
        "4a6ff8cd83f1b452214d5e5658115e5362316b84127eef6f47426792dc8726c3"
        "4193fd6affff001d00000000"
    };
    if (hex.size() != header.size() * 2) throw std::runtime_error("Invalid header size");
    for (size_t i = 0; i < header.size(); ++i) {
        unsigned int byte_value;
        const auto [ptr, ec] = std::from_chars(hex.data() + i * 2, hex.data() + i * 2 + 2, byte_value, 16);
        if (ec != std::errc{} || ptr != hex.data() + i * 2 + 2) throw std::runtime_error("Invalid header hex");
        header[i] = static_cast<unsigned char>(byte_value);
    }
    SHA256_CTX prefix;
    SHA256_Init(&prefix);
    SHA256_Update(&prefix, header.data(), 64);
    if (DisplayHash(DoubleHash(prefix, header)) != "fe8c9718408e6959fe875c0f8d3182f633744f7a4903e710bd29c225673b8b7f") {
        throw std::runtime_error("Header/hash self-test failed");
    }
    Hash target{};
    target[26] = 0xff;
    target[27] = 0xff;
    Hash above_target = target;
    above_target[0] = 1;
    if (!MeetsTarget(Hash{}) || !MeetsTarget(target) || MeetsTarget(above_target) || MeetsTarget(DoubleHash(prefix, header))) {
        throw std::runtime_error("Proof-of-work target self-test failed");
    }
    if (std::string{argv[1]} == "--self-test") {
        std::cout << "PASS: serialized header, double-SHA256, and difficulty-one target boundaries\n";
        return 0;
    }
    uint64_t next_nonce{0};
    uint32_t timestamp{1795003201};
    {
        std::ifstream input{argv[1]};
        if (input && !(input >> timestamp >> next_nonce)) throw std::runtime_error("Invalid checkpoint");
        if (timestamp < 1795003201 || next_nonce > uint64_t{UINT32_MAX} + 1) throw std::runtime_error("Checkpoint out of range");
    }
    auto save = [&] {
        const std::string temporary = std::string{argv[1]} + ".tmp";
        {
            std::ofstream output{temporary, std::ios::trunc};
            output << timestamp << ' ' << next_nonce << '\n';
            output.flush();
            if (!output) throw std::runtime_error("Cannot write checkpoint");
        }
        if (std::rename(temporary.c_str(), argv[1]) != 0) throw std::runtime_error("Cannot replace checkpoint");
    };
    std::cout << "Self-test passed; resuming time=" << timestamp << " nonce=" << next_nonce << '\n' << std::flush;
    while (true) {
        for (int i = 0; i < 4; ++i) header[68 + i] = timestamp >> (8 * i);
        for (; next_nonce <= UINT32_MAX; ++next_nonce) {
            for (int i = 0; i < 4; ++i) header[76 + i] = next_nonce >> (8 * i);
            const Hash hash = DoubleHash(prefix, header);
            if (MeetsTarget(hash)) {
                save();
                std::cout << "FOUND time=" << timestamp << " nonce=" << next_nonce << " hash=" << DisplayHash(hash) << '\n';
                return 0;
            }
            if ((next_nonce + 1) % 10000000 == 0) {
                // Saving the current nonce repeats one hash at most after a restart.
                save();
                std::cout << "time=" << timestamp << " searched-through=" << next_nonce << '\n' << std::flush;
            }
        }
        if (timestamp == UINT32_MAX) throw std::runtime_error("Timestamp space exhausted");
        ++timestamp;
        next_nonce = 0;
        save();
    }
} catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
}
