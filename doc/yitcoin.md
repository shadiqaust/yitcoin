# Yitcoin experimental network

This branch adds an opt-in `-chain=yitcoin` network. It is **not a public
launch or a production-ready release**. Bitcoin's existing networks are
retained, and omitting `-chain=yitcoin` still selects Bitcoin mainnet.
Do not use real funds, Bitcoin wallets, or hardware-wallet seeds for testing.

## Network identity

| Setting | Yitcoin |
| --- | --- |
| Ticker | YTC |
| Chain selector / config section | `yitcoin` / `[yitcoin]` |
| Network data subdirectory | `yitcoin` |
| P2P port | `19433` |
| RPC port | `19432` |
| P2P message magic | `fa 64 7e b5` |
| Genesis hash | `00000000fac67770c911525f34ff956e78a64bc4cb73a6aa493634bea5545b63` |
| Genesis timestamp / nonce | `1795011864` / `210259129` |
| Segwit address HRP | `yit` |
| Silent Payments HRP | `ysp` |
| Base58 P2PKH / P2SH / private key versions | `38` / `58` / `166` |
| Extended public / private key versions | `0491b21e` / `0491ade4` |
| DNS and fixed seeds | None; peers must be added explicitly |

Identifiers are selected for this prototype, not registered globally or
guaranteed unused by other cryptocurrencies.

## Consensus starting point

The network preserves Bitcoin's SHA256d proof of work, 600-second target
spacing, 2016-block retarget interval, 50-coin starting subsidy, and
210,000-block halving interval. Genesis uses difficulty-one `nBits=0x1d00ffff`,
**not today's Bitcoin network difficulty**.

Bitcoin's historical BIP34, BIP65, BIP66, CSV, and Segwit activation heights
are preserved. Bitcoin-history-specific script exceptions, BIP34 block hash,
minimum chain work, assume-valid hash, and UTXO snapshots are not copied.
This is a development starting point, not a recommendation to reuse those
historical activation heights for a new production chain.

Genesis's output uses Bitcoin's historical public key, but the genesis output
is unspendable because it is not inserted into the spendable UTXO set. The
launch plan reserves 1,000 YTC through the first 20 post-genesis block rewards
(50 YTC each), mined to the founder's Yitcoin address before public launch.
This allocation is visible in the chain; coinbase rewards mature after 100
blocks. It is not a spendable genesis allocation, and testnet coins do not
count toward it. Never assume the historical genesis key is your own address.

## Build and local smoke test

Follow the upstream build instructions for your operating system. A typical
walletless headless build is:

```sh
cmake -S . -B build -DBUILD_GUI=OFF -DENABLE_IPC=OFF -DENABLE_WALLET=OFF
cmake --build build -j2
python3 contrib/yitcoin/smoke_test.py --bindir build/bin
```

This configuration runs a full node but does not include wallet RPCs. To
include them, install SQLite development files and omit
`-DENABLE_WALLET=OFF`; the separate data-directory and RPC safety warnings
still apply.

The smoke test starts two nodes bound only to loopback, disables seed
discovery, creates temporary data directories, verifies genesis proof of work
and peer connectivity, checks that a Yitcoin address is accepted and a Bitcoin
address is rejected, then shuts both down and removes their temporary data.
It does not mine spendable coins or prove post-genesis block synchronization.
The Yitcoin GitHub Actions workflow runs this same build and smoke test for
pull requests.

On a machine with limited memory, use `cmake --build build -j1` instead.

The optional standalone genesis miner requires OpenSSL development headers
(`libssl-dev` on Ubuntu):

```sh
c++ -O3 -std=c++20 -Wno-deprecated-declarations \
  contrib/yitcoin/genesis_miner.cpp -lcrypto -o build/genesis-miner
build/genesis-miner --self-test
build/genesis-miner build/genesis.checkpoint
```

It checks its header/hash against an independent known result before mining,
and saves progress every ten million nonces. Use the same checkpoint file to
resume after interruption. It prints a valid nonce, timestamp, and block hash;
it does not modify chain parameters automatically.

For a manually managed isolated node, use a dedicated new directory:

```sh
mkdir -p "$HOME/yitcoin-dev"
build/bin/bitcoind -chain=yitcoin -datadir="$HOME/yitcoin-dev" \
  -server -connect=0 -listen=0 -dnsseed=0 -fixedseeds=0 \
  -discover=0 -listenonion=0
```

In another terminal:

```sh
build/bin/bitcoin-cli -chain=yitcoin -datadir="$HOME/yitcoin-dev" getblockchaininfo
build/bin/bitcoin-cli -chain=yitcoin -datadir="$HOME/yitcoin-dev" stop
```

The executable names and configuration filename still follow Bitcoin Core
(`bitcoind`, `bitcoin-cli`, and `bitcoin.conf`). Yitcoin's GUI amount unit is
displayed as YTC. Use a separate data directory so existing Bitcoin or
BiitCoin data and wallets are not reused.

## Linux server preparation

Use a supported distribution with GCC 12.1 or newer, CMake 3.22 or newer,
and Python 3.10 or newer; see [dependencies](dependencies.md). For example,
Ubuntu 24.04 can install the headless build prerequisites with:

```sh
sudo apt update
sudo apt install git build-essential cmake python3 libboost-dev
```

After the Yitcoin changes are reviewed, fetch the updated branch into a fresh
clone, then run the build and smoke-test commands above. Run the node
as a normal, unprivileged user, not as root. Keep its data directory separate
from all Bitcoin installations, and leave RPC bound to localhost.

For the first server test use the isolated-node command above. Do not open
firewall ports, configure an automatic startup service, import valuable
keys, or advertise the server as a public Yitcoin node at this stage.

The upstream `-regtest` network is unchanged and remains suitable for fast,
disposable mining experiments; it is not a separate Yitcoin testnet.
Mainnet difficulty-one mining can take billions of hashes per block. A
successful genesis startup does not demonstrate that block production works.

## Before any public launch

The planned sequence is: private mining test, private multi-node testnet,
security and wallet review, public testnet, then public launch. Production
readiness also requires a pinned upstream release, consensus review (including
activation heights), wallet/address tooling review (including a unique wallet
coin type and cross-chain replay protection), independent security review,
reproducible builds, release branding, bootstrap peers/seeds, and a mining
and security plan.

Address prefixes and a separate genesis do not make Bitcoin balances usable
on this network. New network coins have no guaranteed value. Do not expose
RPC to the internet or advertise this prototype as secure.
