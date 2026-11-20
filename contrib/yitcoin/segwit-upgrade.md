# DRAFT: coordinated Yitcoin SegWit upgrade

**Do not deploy this branch or resume mining until the regression and miner
integration checks pass and every participant agrees on activation.**

## What failed

The live node at height 226 admitted a signed witness transaction to its
mempool. Block assembly included it even though Yitcoin retained Bitcoin's
SegWit activation height, 481824. The candidate failed its own validation with
`unexpected-witness`. The block-script flags include WITNESS independently of
the block-level deployment; seeing WITNESS there is not proof of activation.
This was not an incorrect fee, a damaged wallet, or an invalid old block.

## Proposed change, not deployment approval

- Activate SegWit block rules starting at **block 250**, not retroactively.
- Keep all rules for blocks 0–249, the genesis, network identity, subsidy
  schedule, and 2% subsidy-only owner payment unchanged.
- Before activation, omit witness-bearing transaction chunks and their
  dependent chunks from mining templates. Leave the transactions in the
  mempool for possible inclusion once activation occurs.
- At height 250, include eligible witness transactions with a valid witness
  commitment and coinbase witness. Transaction fees still go to the miner.
- Do not alter Bitcoin or other networks' default deployment heights.

250 is a **proposal**, based on the reported paused tip at 226. If any node
has reached 250 using the previous rules, stop: this height must be
reassessed before use. This branch does not automatically find or authorize
a safe height. Changing a deployed activation height later can split history.

## Verification gates

The `Yitcoin SegWit activation regression` workflow uses three disposable
loopback-only Yitcoin regression nodes with a simulated transition at 250.
It makes a signed 1 YTC wallet transfer at height 226, checks that block 227
can be templated without witness, rejects a premature witness block, reloads
the pending payment after restart, mines to 249, confirms the payment at 250,
checks owner/miner fee allocation, checks old-rule rejection, restarts, and
verifies the full synthetic chain.

Regtest halves at 150, so its block 250 subsidy is 25 YTC and its owner share
is 0.5 YTC. On the live chain, subsidy remains 50 YTC at 250, split 49/1 plus
fees to the miner. Parameter tests pin the live activation at 250 and retain
Bitcoin's 481824. Existing smoke tests verify the original main genesis.

The owner integration workflow pins the miner with the corrected coinbase
witness serialization. An old cached ZIP is not sufficient evidence of miner
compatibility. Validate the exact binaries that will be installed.

These tests do **not** access, copy, or prove the validity of the user's
server database. A separate offline check of a stopped-node backup is needed
before deployment. Never upload wallets, cookie files, configuration secrets,
or private keys to GitHub.

## Coordinated rollout checklist (after review, not commands to run now)

1. Pause all miners and confirm every node's tip hash and height. Resolve any
   differences. Confirm the current tip is below 250.
2. Back up each wallet securely using `backupwallet`. Stop each node cleanly
   before making filesystem copies of its full datadir. Keep old binaries.
3. On an isolated copy of the stopped Linux node's chain, test the candidate
   binary with networking disabled and `verifychain 4 0`. Confirm the same tip
   hash at 226 (or the agreed current tip), pending transfer, and valid template.
   Do not expose the copy to the real P2P network or run miners against it.
4. Build replacement Linux, Windows GUI, Windows node, and macOS packages from
   the same approved fix revision. Update all nodes, including external users'
   nodes; the existing Windows ZIP does not contain this fix.
5. Verify `getdeploymentinfo` reports SegWit activation at 250, the tip has not
   changed unexpectedly, and `getblocktemplate` succeeds on all mining nodes.
6. Only after an explicit deployment decision, resume compatible miners.
   Pending witness transactions are omitted through 249, then become eligible
   at 250. Confirm the owner payout and transfer, and compare node tip hashes.

Old nodes will reject witness-bearing activation blocks. A backward binary
rollback after activation is not safe: keep mining paused and coordinate
recovery rather than resetting wallets or deleting chain data.

Until activation, avoid creating additional witness spends. Do not resend
the existing pending payment: it may confirm after the coordinated upgrade.
