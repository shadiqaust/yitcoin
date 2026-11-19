"""Check the packaged Windows GUI, wallet, and Yitcoin chain without public peers."""

import argparse
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindir", type=Path, required=True)
    bindir = parser.parse_args().bindir.resolve()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="yitcoin-gui-smoke-") as root:
        common = ["-chain=yitcoin-regtest", f"-datadir={root}", f"-rpcport={port}"]
        gui = subprocess.Popen([
            str(bindir / "bitcoin-qt.exe"), *common,
            "-server=1", "-listen=0", "-connect=0", "-dnsseed=0",
            "-fixedseeds=0", "-discover=0", "-listenonion=0", "-natpmp=0",
            "-rpcbind=127.0.0.1", "-rpcallowip=127.0.0.1",
            "-nosettings", "-splash=0", "-min",
        ])

        def rpc(*args):
            result = subprocess.run([
                str(bindir / "bitcoin-cli.exe"), *common, *args,
            ], capture_output=True, text=True, timeout=20, check=True)
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return result.stdout.strip()

        try:
            deadline = time.monotonic() + 120
            while True:
                if gui.poll() is not None:
                    raise RuntimeError(f"Packaged GUI exited early: {gui.returncode}")
                try:
                    info = rpc("getblockchaininfo")
                    break
                except subprocess.CalledProcessError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
            assert info["chain"] == "yitcoin-regtest", info
            try:
                rpc("getblocktemplate", '{"rules":["segwit"]}')
                raise AssertionError("GBT accepted a client that did not advertise owner-reward support")
            except subprocess.CalledProcessError as error:
                assert "yitcoin-owner-reward" in error.stderr, error.stderr
            template = rpc("getblocktemplate", '{"rules":["segwit"],"capabilities":["yitcoin-owner-reward"]}')
            assert template["yitcoin_owner_reward"] == 100_000_000, template
            owner_script = "0014c4b1e20b9ab28e50dcfd7238974f83ae0d5699a6"
            assert template["yitcoin_owner_script"] == owner_script, template
            rpc("createwallet", "gui-smoke")
            address = rpc("-rpcwallet=gui-smoke", "getnewaddress")
            assert address.startswith("tyit1"), address
            hashes = rpc("generatetoaddress", "1", address)
            assert len(hashes) == 1, hashes
            assert rpc("getblockchaininfo")["blocks"] == 1
            block = rpc("getblock", hashes[0], "2")
            coinbase_outputs = block["tx"][0]["vout"]
            paid_outputs = [output for output in coinbase_outputs if output["value"] > 0]
            assert sorted(output["value"] for output in paid_outputs) == [1, 49], paid_outputs
            assert any(
                output["scriptPubKey"]["hex"] == owner_script and output["value"] == 1
                for output in paid_outputs
            ), paid_outputs
            balances = rpc("-rpcwallet=gui-smoke", "getbalances")
            assert balances["mine"]["immature"] == 49, balances
            print(
                "PASS: packaged GUI launches, serves RPC, creates a wallet, "
                "and validates the 49/1 Yitcoin reward split"
            )
        finally:
            if gui.poll() is None:
                try:
                    rpc("stop")
                    gui.wait(timeout=30)
                except (subprocess.SubprocessError, OSError):
                    gui.kill()
                    gui.wait(timeout=15)


if __name__ == "__main__":
    main()
