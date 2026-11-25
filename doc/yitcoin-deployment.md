# Yitcoin: update Linux, add Windows/Mac nodes, and mine

These instructions use the **node and CLI** artifacts from:
https://github.com/shadiqaust/yitcoin/actions/runs/44708149027

Source commit: `506ef1b12602c5a39a97f2ed8d6cbab660f30e73`.
All four platform packaging/smoke jobs passed. That does not mean the full
upstream CI suite has completed or that this is a production-audited release.
The packages are unsigned experimental builds. They include wallet RPC support,
but **not the desktop GUI or a mining executable**. Executables still use the
names `bitcoind` and `bitcoin-cli`; always specify `-chain=yitcoin`.

Do not paste terminal prompts such as `$`, `PS C:\>`, or `user@server` with commands.
Commands below never delete chain data or existing wallets.

## 1. Download and verify the correct artifact

Sign in to GitHub, open the run linked above, and scroll to **Artifacts**:

| Computer | Artifact |
| --- | --- |
| Linux x86_64 | `yitcoin-linux-x86_64-44708149027` |
| Windows x64 | `yitcoin-windows-x86_64-44708149027` |
| Apple Silicon Mac (M1/M2/M3/M4 or newer ARM) | `yitcoin-macos-arm64-44708149027` |
| Intel Mac | `yitcoin-macos-x86_64-44708149027` |

GitHub downloads an outer ZIP. Extract it first. Inside, locate the platform's
`.tar.gz` (Linux/Mac) or `.zip` (Windows) and its matching `.sha256` file.
There may also be an unpacked platform folder from the artifact uploader.

On Linux, in the directory containing the inner archive:

```bash
sha256sum yitcoin-linux-x86_64.tar.gz
cat yitcoin-linux-x86_64.tar.gz.sha256
```

On Mac (change `arm64` to `x86_64` for Intel):

```bash
shasum -a 256 yitcoin-macos-arm64.tar.gz
cat yitcoin-macos-arm64.tar.gz.sha256
```

On Windows PowerShell:

```powershell
Get-FileHash .\yitcoin-windows-x86_64.zip -Algorithm SHA256
Get-Content .\yitcoin-windows-x86_64.zip.sha256
```

Compare the 64-character hash, ignoring letter case and any filename prefix.
Stop if it differs. These checksums detect corruption; they are not independent
publisher signatures.

## 2. Update the existing Linux chain without starting over

Run as the account that already owns your node, **not root**. The known setup
uses user `yitcoin`, data directory `$HOME/yitcoin-data`, and old binaries under
`$HOME/src/yitcoin-src/build/bin`. Adjust only if your actual paths differ.
Never point the update at an empty data directory by mistake.

### 2.1 Pause mining and check the live chain

Stop your miner with Ctrl+C in its terminal. If backgrounded, find its PID with
`pgrep -a -u "$USER" cpuminer` and terminate only that PID using `kill PID`.
If managed by systemd, stop its actual service instead. Do not use broad
`killall` commands.

```bash
whoami
DATA="$HOME/yitcoin-data"
OLD="$HOME/src/yitcoin-src/build/bin"
"$OLD/bitcoin-cli" -chain=yitcoin -datadir="$DATA" getblockchaininfo
"$OLD/bitcoin-cli" -chain=yitcoin -datadir="$DATA" listwallets
```

**Activation safety:** this build requires the 2% owner subsidy output from
height **200**. The last reported paused height was 180; check again now.
If an old-rules network has reached 200 without the required output, stop here.
Do not erase blocks, reindex hoping to bypass consensus, or restart mining.
That situation needs an activation/chain compatibility review first.
If all nodes are already on the owner-reward rules, height above 200 is not
itself a problem, but establish that before upgrading an unknown installation.

### 2.2 Stop gracefully and make an offline backup

If a supervisor automatically restarts your node, stop that service first
instead of using only the RPC stop command. Identify any second node using its
own data directory and stop it separately before replacing its binaries.

```bash
"$OLD/bitcoin-cli" -chain=yitcoin -datadir="$DATA" stop
pgrep -a -u "$USER" bitcoind || true
```

Wait until the process for this data directory has exited. Do not continue
while it is still writing files. Then:

```bash
BACKUP="$HOME/yitcoin-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
chmod 700 "$HOME/yitcoin-backups" "$BACKUP"
cp -a "$DATA" "$BACKUP/node-data"
cp -a "$OLD" "$BACKUP/old-bin"
```

This can require substantial disk space. Check `df -h "$HOME"` first.
The backup contains private wallet material: keep it offline/private, never
upload it to GitHub. Keep all miners paused until every validating node is
updated.

### 2.3 Extract the downloaded Linux archive

Put the verified inner archive in `$HOME/Downloads` (or adjust that path).
Install to a new directory rather than overwriting the old build:

```bash
mkdir -p "$HOME/opt"
tar -xzf "$HOME/Downloads/yitcoin-linux-x86_64.tar.gz" -C "$HOME/opt"
BIN="$HOME/opt/yitcoin-linux-x86_64/bin"
cat "$HOME/opt/yitcoin-linux-x86_64/SOURCE_COMMIT.txt"
"$BIN/bitcoind" --version
ldd "$BIN/bitcoind"
ldd "$BIN/bitcoin-cli"
```

The source-commit file should match the commit at the top of this guide.
If `ldd` reports `not found`, install the named runtime library before starting.
This package was built on Ubuntu 24.04; older distributions may have an
incompatible glibc. Do not replace system glibc manually. Use a compatible OS
or rebuild for the target OS. Do not assume Mac/Windows packages run on Linux.

### 2.4 Start with the SAME data directory and config

```bash
"$BIN/bitcoind" -chain=yitcoin -datadir="$DATA" -daemon
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" -rpcwait getblockchaininfo
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" getnetworkinfo
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" listwallets
```

Confirm `"chain": "yitcoin"` and the old height/hash have been retained.
Starting at height 0 unexpectedly usually means the wrong data directory.
If an existing wallet is not loaded, load it; do not recreate it:

```bash
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" loadwallet "ytc-miner"
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" -rpcwallet=ytc-miner getbalances
ss -lnt | grep -E ':(19432|19433)\b'
```

Expected: RPC `19432` bound only to loopback (`127.0.0.1` / `::1`).
P2P `19433` may bind publicly if you intend to accept peers.
If using systemd, change the service's executable path to the new `BIN` and
keep its existing data/config arguments. Do not run both a manual and systemd
instance against the same directory. Use `systemctl cat YOUR_NODE_SERVICE`
to inspect its actual settings before editing.

## 3. Start a new Windows node

Use PowerShell as a normal Windows user. Extract the verified inner ZIP:

```powershell
New-Item -ItemType Directory -Force "$HOME\yitcoin-app" | Out-Null
Expand-Archive -Path "$HOME\Downloads\yitcoin-windows-x86_64.zip" -DestinationPath "$HOME\yitcoin-app"
$Bin = "$HOME\yitcoin-app\yitcoin-windows-x86_64\bin"
$Data = "$HOME\yitcoin-data"
New-Item -ItemType Directory -Force $Data | Out-Null
Get-Content "$HOME\yitcoin-app\yitcoin-windows-x86_64\SOURCE_COMMIT.txt"
& "$Bin\bitcoind.exe" --version
```

Retain the DLLs beside the `.exe` files. If dependencies are missing, install
the official Microsoft Visual C++ x64 runtime; never download random DLLs.

Choose a reachable Yitcoin server. The previously used server was
`seed.yitcoin.com:19433`; use it only if it is still your server and upgraded.
Check connectivity before starting:

```powershell
$Peer = "seed.yitcoin.com:19433"
Test-NetConnection -ComputerName seed.yitcoin.com -Port 19433
& "$Bin\bitcoind.exe" -chain=yitcoin "-datadir=$Data" "-addnode=$Peer" -server=1 -rpcbind=127.0.0.1 -rpcallowip=127.0.0.1
```

The last command stays running in that terminal. Do not close it or use
`-daemon` on Windows. Open a **second PowerShell window**:

```powershell
$Bin = "$HOME\yitcoin-app\yitcoin-windows-x86_64\bin"
$Data = "$HOME\yitcoin-data"
& "$Bin\bitcoin-cli.exe" -chain=yitcoin "-datadir=$Data" -rpcwait getblockchaininfo
& "$Bin\bitcoin-cli.exe" -chain=yitcoin "-datadir=$Data" getconnectioncount
& "$Bin\bitcoin-cli.exe" -chain=yitcoin "-datadir=$Data" getpeerinfo
```

Wait until the height/hash match the Linux server and initial block download
finishes. No inbound laptop firewall port is needed for an outbound connection.
Never allow public access to RPC port 19432.

Create a NEW laptop wallet once:

```powershell
& "$Bin\bitcoin-cli.exe" -chain=yitcoin "-datadir=$Data" createwallet "laptop-miner"
& "$Bin\bitcoin-cli.exe" -chain=yitcoin "-datadir=$Data" -rpcwallet=laptop-miner getnewaddress
& "$Bin\bitcoin-cli.exe" -chain=yitcoin "-datadir=$Data" -rpcwallet=laptop-miner getbalances
```

If already created, use `loadwallet "laptop-miner"` instead of `createwallet`.
Keep the returned address for mining payouts. It is public; private keys and
wallet backups are not. A synced node does not automatically mine.

Graceful stop:

```powershell
& "$Bin\bitcoin-cli.exe" -chain=yitcoin "-datadir=$Data" stop
```

## 4. Start a new Mac node

These packages were built on macOS 15. Compatibility with older macOS versions
is not established. In Terminal:

```bash
uname -m
```

`arm64` means the ARM package; `x86_64` means the Intel package. Run the matching
commands below, changing `PLATFORM` for Intel:

```bash
PLATFORM=macos-arm64
mkdir -p "$HOME/opt" "$HOME/yitcoin-data"
tar -xzf "$HOME/Downloads/yitcoin-${PLATFORM}.tar.gz" -C "$HOME/opt"
BIN="$HOME/opt/yitcoin-${PLATFORM}/bin"
DATA="$HOME/yitcoin-data"
cat "$HOME/opt/yitcoin-${PLATFORM}/SOURCE_COMMIT.txt"
"$BIN/bitcoind" --version
otool -L "$BIN/bitcoind"
otool -L "$BIN/bitcoin-cli"
```

If macOS blocks this unsigned build, review it before granting approval in
System Settings → Privacy & Security. Do not disable Gatekeeper globally.
For missing non-system dylibs reported by `otool`, install matching dependencies
using your normal package manager; the CI build used Homebrew Boost.

```bash
"$BIN/bitcoind" -chain=yitcoin -datadir="$DATA" \
  -addnode=seed.yitcoin.com:19433 -server=1 \
  -rpcbind=127.0.0.1 -rpcallowip=127.0.0.1 -daemon
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" -rpcwait getblockchaininfo
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" getconnectioncount
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" createwallet "mac-miner"
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" -rpcwallet=mac-miner getnewaddress
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" -rpcwallet=mac-miner getbalances
```

Again, use your upgraded server's P2P address if different; wait for sync.
Use `loadwallet "mac-miner"` on subsequent starts if it is not already loaded.
Stop with:

```bash
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" stop
```

## 5. Mining: a separate compatible executable is required

The node packages above **do not include cpuminer**. The compatible source is:
https://github.com/shadiqaust/cpuminer-opt

Owner-reward support was merged in PR 1:
https://github.com/shadiqaust/cpuminer-opt/pull/1

The known feature commit is
`6b35302afac26659d77e13af14fa1e15f86a4f41`.
An unrelated upstream cpuminer binary will not necessarily support Yitcoin's
required coinbase split. Do not restart an old miner at/after block 200.
There is no verified native Windows/Mac miner download in this guide.

### 5.1 Build the compatible miner on x86_64 Ubuntu/Debian

These are Linux commands, not PowerShell or macOS commands. The build uses
`-march=native`: build on the CPU you will actually mine with.

```bash
sudo apt-get update
sudo apt-get install -y git build-essential automake autoconf libtool pkg-config \
  libcurl4-openssl-dev libjansson-dev libssl-dev libgmp-dev zlib1g-dev
mkdir -p "$HOME/src"
git clone https://github.com/shadiqaust/cpuminer-opt.git "$HOME/src/yitcoin-cpuminer"
cd "$HOME/src/yitcoin-cpuminer"
git checkout --detach 6b35302afac26659d77e13af14fa1e15f86a4f41
./autogen.sh
CFLAGS="-O3 -march=native -Wall" ./configure --with-curl
make -j2
./cpuminer --version
```

If this fails, stop and retain the error. These compile instructions do not
constitute a verified build for every CPU/OS.

### 5.2 Prepare local-only RPC access for the miner

On the Linux NODE machine, edit the existing `$HOME/yitcoin-data/bitcoin.conf`;
**do not overwrite it**. Retain existing peers, ports, whitelist settings, and
other accounts. Use `share/rpcauth/rpcauth.py` from the Yitcoin source checkout
to generate a dedicated `rpcauth` entry for a `miner` user:

```bash
python3 "$HOME/src/yitcoin-src/share/rpcauth/rpcauth.py" miner
```

The tool prints a new password and the corresponding `rpcauth` line. Keep both
private. Add the `rpcauth` line to the existing config using a local editor;
use the generated password in the miner's local config only. This guide
deliberately does not include credentials.

If your node uses `rpcwhitelist`, the miner needs access to `getblocktemplate`
and `submitblock` plus any additional methods it requests. Review that local
policy separately; do not remove the explorer's restricted account settings.
Restart the node gracefully after editing its config. Keep RPC listening on
127.0.0.1, not 0.0.0.0.

Before mining, as the Linux node account:

```bash
BIN="$HOME/opt/yitcoin-linux-x86_64/bin"
DATA="$HOME/yitcoin-data"
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" getconnectioncount
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" getblocktemplate \
  '{"rules":["segwit"],"capabilities":["yitcoin-owner-reward"]}'
```

The node needs a real connected Yitcoin peer and sufficiently synced chain.
At/after activation, inspect `yitcoin_owner_reward` and `yitcoin_owner_script`
in the template. At a 50 YTC subsidy the required owner amount is 100000000
satoshis (1 YTC). Error -9 means no peer; RPC authorization failure is a
credential/config issue, not a reason to open RPC publicly.

### 5.3 Create the mining config locally

```bash
umask 077
nano "$HOME/yitcoin-miner.json"
```

Enter this structure in the editor, replacing placeholders locally:

```json
{
  "algo": "sha256d",
  "url": "http://127.0.0.1:19432",
  "user": "miner",
  "pass": "REPLACE_LOCALLY_WITH_THE_GENERATED_RPC_PASSWORD",
  "coinbase-addr": "REPLACE_WITH_YOUR_YTC_RECEIVING_ADDRESS",
  "threads": 2
}
```

You can use a receiving address from the Windows or Mac wallet. The payout
belongs to that wallet even if the hashing happens on Linux. Do not copy that
wallet's private keys to the miner. This config is private: never commit,
upload, screenshot, or paste it into chat.

```bash
chmod 600 "$HOME/yitcoin-miner.json"
"$HOME/src/yitcoin-cpuminer/cpuminer" --config="$HOME/yitcoin-miner.json"
```

Start in the foreground so errors are visible. Ctrl+C stops it. Once working:

```bash
mkdir -p "$HOME/log"
nohup "$HOME/src/yitcoin-cpuminer/cpuminer" \
  --config="$HOME/yitcoin-miner.json" \
  > "$HOME/log/yitcoin-miner.log" 2>&1 < /dev/null &
echo $!
tail -f "$HOME/log/yitcoin-miner.log"
```

Record the PID; stop that exact process with `kill PID`. Ctrl+C on `tail`
only stops viewing the log, not the miner.

### 5.4 Actually hash on a Windows or Mac laptop

**Receiving a payout and doing the hashing are different.** A laptop wallet
can receive Linux-mined payouts without running a miner itself.

For hashing on Windows x64, one option is Ubuntu under WSL2, using the Linux
miner build commands above. WSL installation may require Windows administrator
approval and a reboot. The following is an initial PowerShell command, not an
application build command:

```powershell
wsl --install -d Ubuntu
```

Inside Ubuntu/WSL, build the compatible miner, then open an SSH tunnel in a
separate **WSL terminal** to the Linux node:

```bash
ssh -N -L 127.0.0.1:29432:127.0.0.1:19432 yitcoin@seed.yitcoin.com
```

Use your actual SSH account/server. This requires existing SSH access.
Keep the tunnel terminal open. In the WSL miner config use
`"url": "http://127.0.0.1:29432"` and the dedicated **server** miner RPC
credentials. Use the Windows wallet's YTC address for `coinbase-addr`.
Run the miner inside WSL, not Windows PowerShell. RPC stays private and
encrypted in transit. Do not add a public firewall rule for 19432 or 29432.

For Mac, the node package is available but **native miner compatibility has
not been verified here**, especially on Apple Silicon. Do not assume the Linux
x86_64 miner runs on an ARM Mac. The immediate supported arrangement in this
guide is Linux hashing to the Mac wallet's address. Running a Linux VM/native
Mac miner is a separate build-and-test task before claiming Mac CPU mining
works; no prebuilt Mac miner is being supplied.

## 6. Check payouts and stop safely

Check `getbalances` on the machine holding the receiving wallet (Windows,
Mac, or Linux), not necessarily on the hashing machine. On Linux:

```bash
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" getblockchaininfo
"$BIN/bitcoin-cli" -chain=yitcoin -datadir="$DATA" -rpcwallet=ytc-miner getbalances
```

Replace the wallet name as appropriate. Newly mined coinbase outputs are
immature until the 100-block maturity requirement is met; immature does not
mean missing. At the current subsidy, miners receive up to 49 YTC plus fees
and the required owner output receives 1 YTC per activated block.
An accepted-block log alone is not enough: confirm height and wallet outputs
on the receiving node.

If mining returns `inconclusive`, rejected blocks, or stops advancing height,
stop and inspect the node/miner logs rather than repeatedly restarting.
Keep backups before upgrades; never run two processes on one data directory.
Do not import valuable Bitcoin keys into this experimental network.
