#!/usr/bin/env bash
set -Eeuo pipefail

# Build one pinned Yitcoin commit and, unless --build-only is supplied,
# upgrade a local Ubuntu/Debian x86_64 node with a private data backup.
# Does not change bitcoin.conf, replace old binaries, or start a miner.
REPO='https://github.com/shadiqaust/yitcoin.git'
DATA_DIR="${YITCOIN_DATA_DIR:-$HOME/yitcoin-data}"
OLD_BIN="${YITCOIN_OLD_BIN:-}"
JOBS="${YITCOIN_BUILD_JOBS:-1}"
ACTIVATION_HEIGHT="${YITCOIN_ACTIVATION_HEIGHT:-}"
BUILD_ONLY=0
COMMIT=''

usage() {
  cat <<'USAGE'
Usage: deploy-yitcoin-linux.sh --commit <40-hex-commit> [options]

Options:
  --data-dir PATH          Existing Yitcoin data dir (default: ~/yitcoin-data)
  --old-bin PATH           Current bin dir (auto-detected if omitted)
  --activation-height N    Abort if current height is at/above this consensus boundary
  --jobs N                 Build parallelism (default: 1)
  --build-only             Build binaries without stopping or changing the node
  -h, --help               Show this help

Example for the currently merged test change:
  bash deploy-yitcoin-linux.sh --commit 730c947351b3ec7efb184c66169b1015c7a49288 --activation-height 250
USAGE
}
fail() { printf 'STOP: %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --commit) (($# >= 2)) || fail '--commit needs a value'; COMMIT="$2"; shift 2 ;;
    --data-dir) (($# >= 2)) || fail '--data-dir needs a value'; DATA_DIR="$2"; shift 2 ;;
    --old-bin) (($# >= 2)) || fail '--old-bin needs a value'; OLD_BIN="$2"; shift 2 ;;
    --activation-height) (($# >= 2)) || fail '--activation-height needs a value'; ACTIVATION_HEIGHT="$2"; shift 2 ;;
    --jobs) (($# >= 2)) || fail '--jobs needs a value'; JOBS="$2"; shift 2 ;;
    --build-only) BUILD_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

[[ "$COMMIT" =~ ^[0-9a-fA-F]{40}$ ]] || { usage >&2; fail 'Provide a full 40-character commit hash; deployments are pinned, never branch-following.'; }
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || fail '--jobs must be a positive integer.'
[[ -z "$ACTIVATION_HEIGHT" || "$ACTIVATION_HEIGHT" =~ ^[0-9]+$ ]] || fail '--activation-height must be a non-negative integer.'
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || fail 'This script targets x86_64 Linux.'
[[ "$EUID" -ne 0 ]] || fail 'Run as the normal Yitcoin user, not root.'
command -v apt-get >/dev/null || fail 'Ubuntu/Debian with apt-get is required.'
command -v sudo >/dev/null || fail 'sudo is required for build dependencies.'

SHORT="${COMMIT:0:12}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
SOURCE_DIR="$HOME/src/yitcoin-$SHORT-$RUN_ID"
BUILD_DIR="$SOURCE_DIR/build"
NEW_BIN="$BUILD_DIR/bin"

find_target_pids() {
  local pid cmd
  while read -r pid; do
    [[ -r "/proc/$pid/cmdline" ]] || continue
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    if [[ "$cmd" == *"-datadir=$DATA_DIR"* || "$cmd" == *"-datadir $DATA_DIR"* ]]; then
      printf '%s\n' "$pid"
    fi
  done < <(pgrep -u "$(id -u)" -x bitcoind || true)
}

if (( BUILD_ONLY == 0 )); then
  [[ -d "$DATA_DIR" ]] || fail "Existing data directory not found: $DATA_DIR"
  if [[ -z "$OLD_BIN" ]]; then
    for candidate in \
      "$HOME/opt/yitcoin-linux-x86_64/bin" \
      "$HOME/src/yitcoin-src/build/bin" \
      "$HOME/src/yitcoin/build/bin"; do
      if [[ -x "$candidate/bitcoin-cli" && -x "$candidate/bitcoind" ]]; then OLD_BIN="$candidate"; break; fi
    done
  fi
  [[ -n "$OLD_BIN" && -x "$OLD_BIN/bitcoin-cli" && -x "$OLD_BIN/bitcoind" ]] || \
    fail 'Could not find current bitcoind/bitcoin-cli. Set --old-bin /path/to/bin.'
  if pgrep -u "$(id -u)" -x cpuminer >/dev/null 2>&1 || pgrep -u "$(id -u)" -x cpuminer-opt >/dev/null 2>&1; then
    fail 'A local miner is running. Pause mining on every machine before updating.'
  fi
  mapfile -t target_pids < <(find_target_pids)
  [[ ${#target_pids[@]} -eq 1 ]] || fail "Expected one bitcoind using $DATA_DIR; found ${#target_pids[@]}. No node was stopped."
  current_info="$("$OLD_BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA_DIR" getblockchaininfo)" || \
    fail 'Could not query the current node. Check its RPC settings and data dir.'
  read -r chain height < <(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("chain",""),d.get("blocks",-1))' <<<"$current_info")
  [[ "$chain" == yitcoin && "$height" =~ ^[0-9]+$ ]] || fail 'Current data dir did not report a valid Yitcoin height.'
  if [[ -n "$ACTIVATION_HEIGHT" ]] && (( height >= ACTIVATION_HEIGHT )); then
    fail "Current height $height is at/above activation height $ACTIVATION_HEIGHT. Review network compatibility before in-place upgrade."
  fi
  printf 'Current Yitcoin height: %s\n' "$height"
  printf 'Pause miners on Windows/Mac/other servers too; this script checks only this Linux account.\n'
fi

printf 'Installing/checking Ubuntu/Debian build dependencies...\n'
sudo apt-get update
sudo apt-get install -y git cmake build-essential pkg-config python3 libboost-dev libsqlite3-dev libevent-dev
mkdir -p "$HOME/src"
printf 'Fetching pinned source commit %s...\n' "$COMMIT"
git init -q "$SOURCE_DIR"
git -C "$SOURCE_DIR" remote add origin "$REPO"
git -C "$SOURCE_DIR" fetch --depth 1 origin "$COMMIT"
git -C "$SOURCE_DIR" checkout --detach FETCH_HEAD
actual="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
[[ "${actual,,}" == "${COMMIT,,}" ]] || fail "Fetched $actual, not requested $COMMIT."

printf 'Configuring and building bitcoind + bitcoin-cli with %s job(s)...\n' "$JOBS"
cmake -S "$SOURCE_DIR" -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release -DENABLE_WALLET=ON -DBUILD_GUI=OFF \
  -DBUILD_DAEMON=ON -DBUILD_CLI=ON -DBUILD_TESTS=OFF -DWITH_ZMQ=OFF
cmake --build "$BUILD_DIR" --parallel "$JOBS" --target bitcoind bitcoin-cli
[[ -x "$NEW_BIN/bitcoind" && -x "$NEW_BIN/bitcoin-cli" ]] || fail 'Build did not produce both expected binaries.'
"$NEW_BIN/bitcoind" --version
printf 'Build ready at %s\n' "$NEW_BIN"
(( BUILD_ONLY == 0 )) || { printf 'Build-only mode: node and data were not changed.\n'; exit 0; }

current_info="$("$OLD_BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA_DIR" getblockchaininfo)" || \
  fail 'Current node became unavailable during build; shutdown was not attempted.'
read -r chain height < <(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("chain",""),d.get("blocks",-1))' <<<"$current_info")
[[ "$chain" == yitcoin && "$height" =~ ^[0-9]+$ ]] || fail 'Could not revalidate current Yitcoin tip.'
if [[ -n "$ACTIVATION_HEIGHT" ]] && (( height >= ACTIVATION_HEIGHT )); then
  fail "Height is now $height, at/above activation height $ACTIVATION_HEIGHT; node was not stopped."
fi
mapfile -t target_pids < <(find_target_pids)
[[ ${#target_pids[@]} -eq 1 ]] || fail 'Node process changed during build; no shutdown attempted.'

printf '\nThis will stop the current node, back up %s, then start this pinned build with the SAME config and ports.\n' "$DATA_DIR"
printf 'It will not resume mining, edit bitcoin.conf, or overwrite old binaries.\n'
read -r -p 'Type UPDATE to continue: ' answer
[[ "$answer" == UPDATE ]] || fail 'Cancelled; running node/data were not changed.'

"$OLD_BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA_DIR" stop
stopped=0
for _ in $(seq 1 60); do
  mapfile -t target_pids < <(find_target_pids)
  if [[ ${#target_pids[@]} -eq 0 ]]; then stopped=1; break; fi
  sleep 1
done
[[ "$stopped" -eq 1 ]] || fail 'Node did not stop within 60 seconds. Do not start another daemon; inspect the process/service.'

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_root="$HOME/yitcoin-backups"
backup="$backup_root/node-$stamp"
mkdir -p "$backup_root"
chmod 700 "$backup_root"
mkdir -m 700 "$backup"
data_kb="$(du -sk "$DATA_DIR" | awk '{print $1}')"
free_kb="$(df -Pk "$HOME" | awk 'NR==2 {print $4}')"
if (( free_kb < data_kb + 512000 )); then
  printf 'Insufficient space for backup; attempting to restart old node.\n' >&2
  rmdir "$backup" 2>/dev/null || true
  "$OLD_BIN/bitcoind" -chain=yitcoin -datadir="$DATA_DIR" -daemon || true
  fail 'Need at least the data-directory size plus 500 MiB free before backup.'
fi
printf 'Backing up data to %s ...\n' "$backup"
if ! cp -a "$DATA_DIR" "$backup/data"; then
  printf 'Backup failed; attempting to restart old node.\n' >&2
  rm -rf -- "$backup"
  "$OLD_BIN/bitcoind" -chain=yitcoin -datadir="$DATA_DIR" -daemon || true
  fail 'Backup failed. The old node restart was attempted; verify it before retrying.'
fi
printf '%s\n' "$OLD_BIN" > "$backup/old-bin-path.txt"
printf '%s\n' "$COMMIT" > "$backup/new-commit.txt"

printf 'Starting updated node; ports and RPC settings come from the existing config.\n'
"$NEW_BIN/bitcoind" -chain=yitcoin -datadir="$DATA_DIR" -daemon
if ! "$NEW_BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA_DIR" -rpcwait -rpcclienttimeout=60 getblockchaininfo; then
  printf '\nUpdated node did not answer RPC. Recent log (if present):\n' >&2
  [[ ! -f "$DATA_DIR/yitcoin/debug.log" ]] || tail -n 60 "$DATA_DIR/yitcoin/debug.log" >&2
  fail "Do not delete data or start a second node. Backup is at $backup; inspect logs before recovery."
fi
connections="$("$NEW_BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA_DIR" getconnectioncount)"
if [[ "$connections" =~ ^[0-9]+$ ]] && (( connections > 0 )); then
  printf '\nChecking getblocktemplate (without submitting or mining)...\n'
  if ! "$NEW_BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA_DIR" getblocktemplate '{"rules":["segwit"],"capabilities":["yitcoin-owner-reward"]}'; then
    fail "Node started but template check failed. Keep mining paused and inspect logs. Backup: $backup"
  fi
else
  printf '\nNode started with no peers, so template was not tested. Keep mining paused.\n'
fi
printf '\nUpdated node started. Mining was not started. Backup: %s\nNew binaries: %s\n' "$backup" "$NEW_BIN"
printf 'This local build/smoke check does not replace the cancelled GitHub CI suite.\n'
