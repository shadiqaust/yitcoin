# Yitcoin bootstrap hostname

Use `seed.yitcoin.com:19433` as an explicit Yitcoin P2P peer:

```ini
[yitcoin]
addnode=seed.yitcoin.com:19433
```

Place this in your existing data directory's bitcoin.conf, keeping other
settings unchanged. Stop and restart the node normally after changing config.
The GUI launchers in this branch also supply this hostname as an addnode.
This is an ordinary DNS hostname for a P2P node, not a DNS-seeder service.
No genesis, consensus, balances, or wallet data changes are needed.

The website is https://yitcoin.com and the Explorer is
https://explorer.yitcoin.com. Neither is a mining RPC endpoint.

Keep RPC on 127.0.0.1:19432. Local miners continue using that address;
a miner using an SSH tunnel continues using 127.0.0.1:29432. Only the
SSH destination hostname changes. Never publish RPC to the internet.

Older packages may still have the previous bootstrap IP in their launcher.
Use newly tested packages or edit the launcher/config locally; no Core binary
recompile is required solely to change an addnode hostname. Check each
package's source commit and smoke-test result before installing.
