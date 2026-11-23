#!/usr/bin/env python3
"""Headless launch and wallet-RPC smoke test for Yitcoin's Qt GUI package."""
import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


def cli_call(cli: str, datadir: Path, *args: str, timeout: int = 8) -> str:
    command = [cli, "-chain=yitcoin", f"-datadir={datadir}", "-rpcclienttimeout=4", *args]
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"bitcoin-cli failed ({result.returncode}): {' '.join(args)}\n{result.stdout}")
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gui", required=True, help="Path to the packaged Qt GUI executable")
    parser.add_argument("--cli", required=True, help="Path to the matching bitcoin-cli executable")
    args = parser.parse_args()
    gui = str(Path(args.gui).resolve())
    cli = str(Path(args.cli).resolve())
    if not Path(gui).is_file() or not Path(cli).is_file():
        raise SystemExit("GUI or CLI binary does not exist")

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    with tempfile.TemporaryDirectory(prefix="yitcoin-gui-smoke-") as temporary:
        datadir = Path(temporary)
        log_path = datadir / "gui.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [gui, "-platform", "offscreen", "-chain=yitcoin", f"-datadir={datadir}",
                 "-server=1", "-listen=0", "-connect=0", "-dnsseed=0", "-fixedseeds=0"],
                stdout=log, stderr=subprocess.STDOUT, env=env,
            )
            try:
                deadline = time.monotonic() + 90
                info = None
                last_error = "node RPC is not ready yet"
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f"GUI exited early with status {process.returncode}")
                    try:
                        raw = cli_call(cli, datadir, "-rpcwait", "getblockchaininfo", timeout=6)
                        info = json.loads(raw)
                        break
                    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
                        last_error = str(error)
                        time.sleep(2)
                if info is None:
                    raise RuntimeError(f"GUI RPC did not become ready: {last_error}")
                if info.get("chain") != "yitcoin":
                    raise RuntimeError(f"GUI started on the wrong chain: {info.get('chain')!r}")

                cli_call(cli, datadir, "createwallet", "gui-smoke-wallet")
                wallet = json.loads(cli_call(cli, datadir, "-rpcwallet=gui-smoke-wallet", "getwalletinfo"))
                if wallet.get("walletname") != "gui-smoke-wallet":
                    raise RuntimeError(f"Wallet RPC returned unexpected wallet: {wallet}")
                cli_call(cli, datadir, "stop")
                process.wait(timeout=30)
                print("GUI launch, Yitcoin chain selection, wallet creation, and wallet RPC passed.")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
                if process.returncode not in (0, None):
                    log.flush()
                    print(log_path.read_text(encoding="utf-8", errors="replace")[-8000:])


if __name__ == "__main__":
    main()
