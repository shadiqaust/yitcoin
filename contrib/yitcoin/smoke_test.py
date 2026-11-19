"""Run loopback-only Yitcoin peer and private-mining smoke tests."""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time


GENESIS_TIME = 1795011864
GENESIS_NONCE = 210259129
GENESIS_HASH = "00000000fac67770c911525f34ff956e78a64bc4cb73a6aa493634bea5545b63"
REGTEST_GENESIS_TIME = 1795011865
REGTEST_GENESIS_NONCE = 0
REGTEST_GENESIS_HASH = "0918042ee192a85b8e64ade1a2de367ea07ebedbb2f0f10552ac6103d089576f"
OWNER_SCRIPT = "0014c4b1e20b9ab28e50dcfd7238974f83ae0d5699a6"
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

def reward_proposal(template, outputs):
    """Serialize a transaction-free candidate for proposal-mode validation."""
    height = template["height"]
    assert 1 <= height <= 16, height
    script_sig = bytes([0x50 + height, 0])
    coinbase = struct.pack("<I", 2) + b"\x01" + bytes(32) + b"\xff" * 4
    coinbase += bytes([len(script_sig)]) + script_sig + b"\xff" * 4
    coinbase += bytes([len(outputs)])
    for amount, script in outputs:
        assert len(script) < 253
        coinbase += struct.pack("<Q", amount) + bytes([len(script)]) + script
    coinbase += struct.pack("<I", height - 1)
    merkle_root = hashlib.sha256(hashlib.sha256(coinbase).digest()).digest()
    header = struct.pack("<I", template["version"])
    header += bytes.fromhex(template["previousblockhash"])[::-1] + merkle_root
    header += struct.pack("<III", template["curtime"], int(template["bits"], 16), 0)
    return (header + b"\x01" + coinbase).hex()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindir", type=Path, required=True)
    parser.add_argument("--miner", type=Path, help="Optionally verify the compatible cpuminer fork")
    options = parser.parse_args()
    bindir = options.bindir.resolve()
    processes = []
    node_processes = []
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
                node = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                processes.append(node)
                node_processes.append(node)
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

            def log_tail(path):
                try:
                    return "\n".join(path.read_text(errors="replace").splitlines()[-40:])
                except OSError:
                    return "<log unavailable>"

            def wait_for(predicate, description, watched_processes=()):
                deadline = time.monotonic() + 120
                last_error = None
                while time.monotonic() < deadline:
                    if any(process.poll() is not None for process in node_processes):
                        raise RuntimeError("A test node exited before the smoke test finished")
                    for name, process, output_path in watched_processes:
                        if process.poll() is not None:
                            raise RuntimeError(
                                f"{name} exited with code {process.returncode}:\n{log_tail(output_path)}"
                            )
                    try:
                        if predicate():
                            return
                    except (RuntimeError, subprocess.TimeoutExpired) as error:
                        last_error = error
                    time.sleep(0.25)
                output = "".join(
                    f"\n{name} output:\n{log_tail(output_path)}"
                    for name, _, output_path in watched_processes
                )
                raise RuntimeError(f"Timed out waiting for {description}: {last_error}{output}")

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
            regtest_node = subprocess.Popen(
                regtest_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            processes.append(regtest_node)
            node_processes.append(regtest_node)
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
            try:
                call(2, "getblocktemplate", '{"rules":["segwit"]}')
            except RuntimeError as error:
                assert "yitcoin-owner-reward" in str(error), error
            else:
                raise AssertionError("GBT accepted a mining client without owner-reward support")
            template = call(
                2,
                "getblocktemplate",
                '{"rules":["segwit"],"capabilities":["yitcoin-owner-reward"]}',
            )
            assert template["coinbasevalue"] == 5_000_000_000, template
            assert template["yitcoin_owner_reward"] == 100_000_000, template
            assert template["yitcoin_owner_script"] == OWNER_SCRIPT, template
            owner_script = bytes.fromhex(OWNER_SCRIPT)
            reward_cases = [
                ([(4_900_000_000, b"\x51"), (100_000_000, owner_script)], ""),
                ([(5_000_000_000, b"\x51")], "bad-cb-owner-reward"),
                ([(4_900_000_001, b"\x51"), (99_999_999, owner_script)], "bad-cb-owner-reward"),
                ([(4_900_000_000, b"\x51"), (100_000_000, b"\x52")], "bad-cb-owner-reward"),
                ([(4_900_000_001, b"\x51"), (100_000_000, owner_script)], "bad-cb-amount"),
            ]
            for outputs, expected in reward_cases:
                proposal = reward_proposal(template, outputs)
                result = call(2, "getblocktemplate", json.dumps({"mode": "proposal", "data": proposal}))
                assert result == expected, (outputs, expected, result)
            mined_hashes = call(2, "generatetoaddress", "1", test_address)
            assert len(mined_hashes) == 1, mined_hashes
            mined_info = call(2, "getblockchaininfo")
            assert mined_info["blocks"] == 1, mined_info
            assert mined_info["bestblockhash"] == mined_hashes[0]
            coinbase_outputs = call(2, "getblock", mined_hashes[0], "2")["tx"][0]["vout"]
            paid_outputs = [output for output in coinbase_outputs if output["value"] > 0]
            assert sorted(output["value"] for output in paid_outputs) == [1, 49], paid_outputs
            assert any(
                output["scriptPubKey"]["hex"] == OWNER_SCRIPT and output["value"] == 1
                for output in paid_outputs
            ), paid_outputs
            if options.miner:
                cookie = (regtest_datadir / "yitcoin-regtest" / ".cookie").read_text().strip()
                miner_config = Path(root) / "miner.json"
                miner_config.write_text(json.dumps({
                    "algo": "sha256d",
                    "url": f"http://127.0.0.1:{regtest_rpc}",
                    "userpass": cookie,
                    "coinbase-addr": test_address,
                    "threads": 1,
                    "no-getwork": True,
                    "no-longpoll": True,
                }))
                miner_config.chmod(0o600)
                miner_log = Path(root) / "miner.log"
                with miner_log.open("w") as output:
                    miner = subprocess.Popen(
                        [str(options.miner.resolve()), f"--config={miner_config}"],
                        stdout=output, stderr=subprocess.STDOUT,
                    )
                processes.append(miner)
                wait_for(
                    lambda: call(2, "getblockcount") >= 2,
                    "cpuminer owner-reward block",
                    watched_processes=(("cpuminer", miner, miner_log),),
                )
                miner.terminate()
                miner.wait(timeout=30)
                # Do not include a deliberately stopped miner in node-liveness checks.
                processes.remove(miner)
                miner_block = call(2, "getblock", call(2, "getblockhash", "2"), "2")
                miner_outputs = miner_block["tx"][0]["vout"]
                assert sorted(output["value"] for output in miner_outputs if output["value"] > 0) == [1, 49]
                assert any(
                    output["scriptPubKey"]["hex"] == OWNER_SCRIPT and output["value"] == 1
                    for output in miner_outputs
                ), miner_outputs
                print("PASS: the compatible cpuminer mined an accepted 49/1 reward block")
            print(
                "PASS: two Yitcoin peers, mainnet genesis PoW, private-regtest genesis, "
                "private-regtest owner reward and GBT capability, one on-demand mined block, "
                "and network-specific addresses"
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
