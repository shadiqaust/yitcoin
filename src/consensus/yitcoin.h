// Copyright (c) 2026-present The Yitcoin developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef BITCOIN_CONSENSUS_YITCOIN_H
#define BITCOIN_CONSENSUS_YITCOIN_H

#include <consensus/amount.h>

/** Return 2% of a Yitcoin block subsidy, rounded down to the nearest satoshi. */
inline CAmount YitcoinOwnerReward(CAmount subsidy) noexcept
{
    return subsidy / 50;
}

#endif // BITCOIN_CONSENSUS_YITCOIN_H
