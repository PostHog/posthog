import { Badge } from '@posthog/quill-primitives'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils/strings'

import { formatNumber } from '../dashboard/formatters'

// Doubling and halving are the same size of change, so both earn the badge.
const BIG_GROWTH_PCT = 100
const BIG_DROP_PCT = -50

export function TrendCell({ totalCalls, previousCalls }: { totalCalls: number; previousCalls: number }): JSX.Element {
    const calls = pluralize(totalCalls, 'call')
    if (previousCalls === 0) {
        return (
            <Tooltip title={`${calls}, none in the previous period`}>
                <span tabIndex={0}>
                    <Badge variant="info">New</Badge>
                </span>
            </Tooltip>
        )
    }
    const pctChange = Math.round(((totalCalls - previousCalls) / previousCalls) * 100)
    const label = `${pctChange > 0 ? '+' : ''}${pctChange.toLocaleString()}%`
    return (
        <Tooltip title={`${calls} vs ${formatNumber(previousCalls)} in the previous period`}>
            <span className="tabular-nums" tabIndex={0}>
                {pctChange >= BIG_GROWTH_PCT || pctChange <= BIG_DROP_PCT ? (
                    <Badge variant="info">{label}</Badge>
                ) : (
                    label
                )}
            </span>
        </Tooltip>
    )
}
