#!/usr/bin/env python3
"""Test a real wallet transfer across Yitcoin's proposed SegWit activation.

Only disposable, loopback-only yitcoin-regtest datadirs are used. The third
node deliberately retains the old activation height to demonstrate why all
nodes must upgrade. No connection is made to the live Yitcoin network.
"""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from smoke_test import OWNER_SCRIPT, free_port

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "test" / "functional"))
from test_framework.blocktools import add_witness_commitment, create_block, create_coinbase
from test_framework.messages import COIN, CTxOut
from test_framework.script import CScript


ACTIVATION_HEIGHT = 250
GBT_REQUEST = {"rules": ["segwit"], "capabilities": ["yitcoin-owner-reward"]}


class Node:
    reserved_ports = set()

    @classmethod
    def next_port(cls):
        while (port := free_port()) in cls.reserved_ports:
            pass
        cls.reserved_ports.add(port)
        return port

    def __init__(self, bindir, datadir, activation):
        self.bindir = bindir
        self.datadir = datadir
        datadir.mkdir()
        self.rpcport = self.next_port()
        self.p2pport = self.next_port()
        self.activation = activation
        self.process = None
        self.start()

    def start(self):
        self.process = subprocess.Popen([
            str(self.bindir / "bitcoind"),
            "-chain=yitcoin-regtest", f"-datadir={self.datadir}",
            "-server=1", "-connect=0", "-dnsseed=0", "-fixedseeds=0",
            "-discover=0", "-listenonion=0", "-natpmp=0",
            f"-bind=127.0.0.1:{self.p2pport}", f"-port={self.p2pport}",
            "-rpcbind=127.0.0.1", "-rpcallowip=127.0.0.1",
            f"-rpcport={self.rpcport}", f"-testactivationheight=segwit@{self.activation}",
            "-fallbackfee=0.00001000",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.wait_for(lambda: self.call("getblockchaininfo"), "RPC startup")

    def call(self, *args, wallet=None):
        command = [
            str(self.bindir / "bitcoin-cli"), "-chain=yitcoin-regtest",
            f"-datadir={self.datadir}", f"-rpcport={self.rpcport}",
            "-rpcclienttimeout=15",
        ]
        if wallet is not None:
            command.append(f"-rpcwallet={wallet}")
        command += [json.dumps(arg) if isinstance(arg, (dict, list, bool)) else str(arg) for arg in args]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        try:
            return json.loads(result.stdout, parse_float=Decimal)
        except json.JSONDecodeError:
            return result.stdout.strip()

    def wait_for(self, predicate, description):
        deadline = time.monotonic() + 60
        last_error = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Node exited while waiting for {description}")
            try:
                if predicate():
                    return
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                last_error = error
            time.sleep(0.1)
        raise RuntimeError(f"Timed out waiting for {description}: {last_error}")

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                self.call("stop")
            finally:
                try:
                    self.process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()


def connect(source, target):
    source.call("addnode", f"127.0.0.1:{target.p2pport}", "onetry")
    source.wait_for(
        lambda: any(peer.get("version", 0) > 0 for peer in source.call("getpeerinfo")),
        "peer handshake",
    )


def sync_tip(source, *targets):
    expected = source.call("getbestblockhash")
    for target in targets:
        target.wait_for(lambda: target.call("getbestblockhash") == expected, "matching tips")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindir", type=Path, required=True)
    parser.add_argument("--logdir", type=Path)
    args = parser.parse_args()
    nodes = []
    with tempfile.TemporaryDirectory(prefix="yitcoin-segwit-") as directory:
        try:
            root = Path(directory)
            for index, activation in enumerate((ACTIVATION_HEIGHT, ACTIVATION_HEIGHT, 481824)):
                nodes.append(Node(args.bindir.resolve(), root / str(index), activation))
            sender, receiver, old_rules = nodes
            sender.call("createwallet", "sender")
            receiver.call("createwallet", "receiver")
            address = sender.call("getnewaddress", "", "bech32", wallet="sender")
            receive_address = receiver.call("getnewaddress", "", "bech32", wallet="receiver")
            connect(sender, receiver)
            connect(sender, old_rules)
            sender.call("generatetoaddress", 226, address)
            sync_tip(sender, receiver, old_rules)
            historical_tip = sender.call("getbestblockhash")
            assert sender.call("getdeploymentinfo")["deployments"]["segwit"]["active"] is False

            # This is the same operation as the reported 1 YTC wallet transfer.
            txid = sender.call("sendtoaddress", receive_address, 1, wallet="sender")
            tx = sender.call("getrawtransaction", txid, True)
            assert any("txinwitness" in vin for vin in tx["vin"]), tx
            assert tx["hash"] != txid, tx
            sender.wait_for(lambda: txid in receiver.call("getrawmempool"), "transfer relay")

            template = sender.call("getblocktemplate", GBT_REQUEST)
            assert template["height"] == 227, template
            assert txid not in [entry["txid"] for entry in template["transactions"]]
            assert txid in sender.call("getrawmempool"), "Skipped transfer must remain pending"

            # A witness-bearing block is still invalid before activation; do not
            # 'fix' this by bypassing validation or retroactively changing history.
            fee = sender.call("getmempoolentry", txid)["fees"]["base"]
            coinbase = create_coinbase(227, fees=int(fee * COIN))
            owner_amount = 25 * COIN // 50  # regression-chain halving is at 150
            coinbase.vout[0].nValue -= owner_amount
            coinbase.vout.append(CTxOut(owner_amount, CScript(bytes.fromhex(OWNER_SCRIPT))))
            block = create_block(tmpl=template, coinbase=coinbase, txlist=[tx["hex"]])
            add_witness_commitment(block)
            block.hashMerkleRoot = block.calc_merkle_root()
            rejection = sender.call("getblocktemplate", {
                "mode": "proposal", "data": block.serialize().hex(), **GBT_REQUEST,
            })
            assert rejection == "unexpected-witness", rejection
            print("PASS: witness payment retained, block 227 template valid, premature witness rejected")

            # Persist/reload the pending transaction and existing chain without
            # deleting the mempool or rewriting accepted blocks.
            sender.stop()
            sender.start()
            if "sender" not in sender.call("listwallets"):
                sender.call("loadwallet", "sender")
            assert sender.call("getbestblockhash") == historical_tip
            sender.wait_for(lambda: txid in sender.call("getrawmempool"), "mempool reload")
            assert not sender.call("getblocktemplate", GBT_REQUEST)["transactions"]
            connect(sender, receiver)
            connect(sender, old_rules)

            sender.call("generatetoaddress", ACTIVATION_HEIGHT - 1 - 226, address)
            sync_tip(sender, receiver, old_rules)
            assert sender.call("getblockhash", 226) == historical_tip
            assert txid in sender.call("getrawmempool")
            assert old_rules.call("getblockcount") == 249
            template = sender.call("getblocktemplate", GBT_REQUEST)
            assert template["height"] == ACTIVATION_HEIGHT
            assert "!segwit" in template["rules"]
            assert txid in [entry["txid"] for entry in template["transactions"]]
            assert "default_witness_commitment" in template

            block_hash = sender.call("generatetoaddress", 1, address)[0]
            sync_tip(sender, receiver)
            block = sender.call("getblock", block_hash, 2)
            assert txid in [entry["txid"] for entry in block["tx"]]
            assert sender.call("getdeploymentinfo")["deployments"]["segwit"]["active"] is True
            assert receiver.call("gettransaction", txid, wallet="receiver")["confirmations"] == 1
            assert txid not in sender.call("getrawmempool")
            assert sender.call("getblockhash", 226) == historical_tip
            outputs = block["tx"][0]["vout"]
            assert sum(out["value"] for out in outputs if out["scriptPubKey"]["hex"] == OWNER_SCRIPT) == Decimal("0.5")
            assert sum(out["value"] for out in outputs) == Decimal(25) + fee
            assert sum(out["value"] for out in outputs if out["scriptPubKey"].get("address") == address) == Decimal("24.5") + fee
            # Submit explicitly, so rejection is checked rather than inferred
            # merely from the old-rule node not having advanced.
            result = old_rules.call("submitblock", sender.call("getblock", block_hash, 0))
            assert result == "unexpected-witness", result
            assert old_rules.call("getblockcount") == 249
            print("PASS: payment confirms at 250, owner share unchanged, old-rule node rejects activation block")

            sender.stop()
            sender.start()
            if "sender" not in sender.call("listwallets"):
                sender.call("loadwallet", "sender")
            assert sender.call("getbestblockhash") == block_hash
            assert sender.call("verifychain", 4, 0)
            assert sender.call("gettransaction", txid, wallet="sender")["confirmations"] == 1
            print("PASS: post-activation restart and full chain verification")
        finally:
            for node in nodes:
                node.stop()
            if args.logdir:
                args.logdir.mkdir(parents=True, exist_ok=True)
                for index in range(len(nodes)):
                    for log in (root / str(index)).rglob("debug.log"):
                        shutil.copyfile(log, args.logdir / f"node-{index}-debug.log")


if __name__ == "__main__":
    main()
