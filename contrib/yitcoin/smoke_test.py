"""Run loopback-only Yitcoin peer and private-mining smoke tests."""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time


GENESIS_TIME = 1795011864
GENESIS_NONCE = 210259129
GENESIS_HASH = "00000000fac67770c911525f34ff956e78a64bc4cb73a6aa493634bea5545b63"
REGTEST_GENESIS_TIME = 1795011865
REGTEST_GENESIS_NONCE = 0
REGTEST_GENESIS_HASH = "0918042ee192a85b8e64ade1a2de367ea07ebedbb2f0f10552ac6103d089576f"
BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def bech32_polymod(values):
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for bit, generator in enumerate(generators):
            if (top >> bit) & 1:
                checksum ^= generator
    return checksum


def segwit_address(hrp, version, program):
    accumulator = bits = 0
    data = [version]
    for byte in program:
        accumulator = (accumulator << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            data.append((accumulator >> bits) & 31)
    if bits:
        data.append((accumulator << (5 - bits)) & 31)

    expanded_hrp = [ord(char) >> 5 for char in hrp] + [0]
    expanded_hrp += [ord(char) & 31 for char in hrp]
    checksum = bech32_polymod(expanded_hrp + data + [0] * 6) ^ 1
    checksum_data = [(checksum >> (5 * (5 - index))) & 31 for index in range(6)]
    return hrp + "1" + "".join(BECH32_CHARSET[value] for value in data + checksum_data)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindir", type=Path, required=True)
    options = parser.parse_args()
    bindir = options.bindir.resolve()
    processes = []
    with tempfile.TemporaryDirectory(prefix="yitcoin-smoke-") as root:
        clients = []
        try:
            ports = set()
            while len(ports) < 5:
                ports.add(free_port())
            p2p0, rpc0, p2p1, rpc1, regtest_rpc = ports
            for index, (p2p, rpc) in enumerate(((p2p0, rpc0), (p2p1, rpc1))):
                datadir = Path(root) / str(index)
                datadir.mkdir()
                common = ["-chain=yitcoin", f"-datadir={datadir}", f"-rpcport={rpc}"]
                command = [
                    str(bindir / "bitcoind"), *common,
                    "-server", "-connect=0", "-dnsseed=0", "-fixedseeds=0",
                    "-discover=0", "-listenonion=0", "-natpmp=0",
                    f"-bind=127.0.0.1:{p2p}", f"-port={p2p}",
                    "-rpcbind=127.0.0.1", "-rpcallowip=127.0.0.1",
                ]
                processes.append(subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                clients.append([str(bindir / "bitcoin-cli"), *common])

            def call(index, *args):
                result = subprocess.run(
                    clients[index] + list(args), capture_output=True, text=True, timeout=15,
                )
                if result.returncode:
                    raise RuntimeError(result.stderr.strip())
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return result.stdout.strip()

            def wait_for(predicate, description):
                deadline = time.monotonic() + 120
                last_error = None
                while time.monotonic() < deadline:
                    if any(process.poll() is not None for process in processes):
                        raise RuntimeError("A test node exited before the smoke test finished")
                    try:
                        if predicate():
                            return
                    except (RuntimeError, subprocess.TimeoutExpired) as error:
                        last_error = error
                    time.sleep(0.25)
                raise RuntimeError(f"Timed out waiting for {description}: {last_error}")

            for index in range(2):
                wait_for(lambda: call(index, "getblockchaininfo")["chain"] == "yitcoin", "Yitcoin RPC")
                info = call(index, "getblockchaininfo")
                assert info["blocks"] == 0, info
                genesis_hash = call(index, "getblockhash", "0")
                header = bytes.fromhex(call(index, "getblockheader", genesis_hash, "false"))
                digest = hashlib.sha256(hashlib.sha256(header).digest()).digest()
                assert digest[::-1].hex() == genesis_hash
                assert genesis_hash == GENESIS_HASH
                assert int.from_bytes(header[68:72], "little") == GENESIS_TIME
                assert int.from_bytes(header[76:80], "little") == GENESIS_NONCE
                nbits = int.from_bytes(header[72:76], "little")
                assert nbits == 0x1D00FFFF, hex(nbits)
                target = (nbits & 0x7FFFFF) << (8 * ((nbits >> 24) - 3))
                assert int.from_bytes(digest, "little") <= target, "Invalid genesis proof of work"
                assert genesis_hash != "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
                program = hashlib.sha256(b"Yitcoin smoke fixture").digest()[:20]
                yitcoin_address = segwit_address("yit", 0, program)
                assert call(index, "validateaddress", yitcoin_address)["isvalid"]
                assert not call(index, "validateaddress", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")["isvalid"]

            assert call(0, "getblockhash", "0") == call(1, "getblockhash", "0")
            call(0, "addnode", f"127.0.0.1:{p2p1}", "onetry")

            def peers_ready():
                for index in range(2):
                    peers = call(index, "getpeerinfo")
                    if len(peers) != 1 or peers[0]["version"] <= 0 or not peers[0]["subver"]:
                        return False
                return True

            wait_for(peers_ready, "peer version handshake")

            regtest_datadir = Path(root) / "regtest"
            regtest_datadir.mkdir()
            regtest_common = ["-chain=yitcoin-regtest", f"-datadir={regtest_datadir}", f"-rpcport={regtest_rpc}"]
            regtest_command = [
                str(bindir / "bitcoind"), *regtest_common,
                "-server", "-listen=0", "-connect=0", "-dnsseed=0", "-fixedseeds=0",
                "-discover=0", "-listenonion=0", "-natpmp=0",
                "-rpcbind=127.0.0.1", "-rpcallowip=127.0.0.1",
            ]
            processes.append(subprocess.Popen(regtest_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            clients.append([str(bindir / "bitcoin-cli"), *regtest_common])
            wait_for(lambda: call(2, "getblockchaininfo")["chain"] == "yitcoin-regtest", "private Yitcoin regtest RPC")

            regtest_info = call(2, "getblockchaininfo")
            assert regtest_info["blocks"] == 0, regtest_info
            regtest_genesis_hash = call(2, "getblockhash", "0")
            assert regtest_genesis_hash == REGTEST_GENESIS_HASH
            regtest_header = bytes.fromhex(call(2, "getblockheader", regtest_genesis_hash, "false"))
            regtest_digest = hashlib.sha256(hashlib.sha256(regtest_header).digest()).digest()
            assert regtest_digest[::-1].hex() == regtest_genesis_hash
            assert int.from_bytes(regtest_header[68:72], "little") == REGTEST_GENESIS_TIME
            assert int.from_bytes(regtest_header[76:80], "little") == REGTEST_GENESIS_NONCE
            regtest_bits = int.from_bytes(regtest_header[72:76], "little")
            assert regtest_bits == 0x207FFFFF, hex(regtest_bits)
            regtest_target = (regtest_bits & 0x7FFFFF) << (8 * ((regtest_bits >> 24) - 3))
            assert int.from_bytes(regtest_digest, "little") <= regtest_target, "Invalid private regtest genesis proof of work"

            test_program = hashlib.sha256(b"Yitcoin private mining smoke fixture").digest()[:20]
            test_address = segwit_address("tyit", 0, test_program)
            assert call(2, "validateaddress", test_address)["isvalid"]
            mined_hashes = call(2, "generatetoaddress", "1", test_address)
            assert len(mined_hashes) == 1, mined_hashes
            mined_info = call(2, "getblockchaininfo")
            assert mined_info["blocks"] == 1, mined_info
            assert mined_info["bestblockhash"] == mined_hashes[0]
            print(
                "PASS: two Yitcoin peers, mainnet genesis PoW, private-regtest genesis, "
                "one on-demand mined test block, and network-specific addresses"
            )
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
