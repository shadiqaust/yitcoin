# Yitcoin owner block reward

The Yitcoin main network requires a 2% share of the block subsidy to be paid
to the configured owner script beginning at block height 200. At the current
50 YTC subsidy, a block pays 1 YTC to the owner and up to 49 YTC to the miner.
Transaction fees remain available to the miner. Earlier blocks are unchanged.
The owner output is a normal coinbase output and has the same 100-block
maturity requirement as the miner's output. The share halves with the subsidy
and is rounded down to whole satoshis; it does not create extra coins.

The owner payment is a consensus rule, not a voluntary mining setting. A node
with this rule rejects blocks at or after height 200 that do not pay the
required amount. Miners using `getblocktemplate` must advertise the
`yitcoin-owner-reward` capability and honor the returned
`yitcoin_owner_reward` and `yitcoin_owner_script` fields. The Yitcoin cpuminer
fork adds that support.

The private Yitcoin regression network enables the rule from block 1 so the
output split can be exercised in smoke tests. The regression-network payout
script is the same public owner script as mainnet; it is not a separate
production payout.

**Do not install or activate this rule on the live network until the current
tip is confirmed below height 200 and all validating nodes and block producers
are upgraded.**
If the chain has already passed height 200 without the required owner outputs,
this activation height is no longer safe for that chain.
