// Copyright (c) 2026-present The Yitcoin developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef BITCOIN_CONSENSUS_YITCOIN_H
#define BITCOIN_CONSENSUS_YITCOIN_H

#include <consensus/amount.h>

/** Proposed coordinated upgrade. Existing Yitcoin blocks below 250 keep their rules. */
inline constexpr int YITCOIN_SEGWIT_HEIGHT{250};

/** Return 2% of a Yitcoin block subsidy, rounded down to the nearest satoshi. */
inline CAmount YitcoinOwnerReward(CAmount subsidy) noexcept
{
    return subsidy / 50;
}

#endif // BITCOIN_CONSENSUS_YITCOIN_H
