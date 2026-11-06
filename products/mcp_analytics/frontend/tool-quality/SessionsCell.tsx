import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { formatPercentage } from 'lib/utils/numbers'

import { formatNumber } from '../dashboard/formatters'

export function SessionsCell({
    sessions,
    totalSessions,
    previousSessions,
    previousTotalSessions,
}: {
    sessions: number
    totalSessions: number
    previousSessions: number
    previousTotalSessions: number
}): JSX.Element {
    const hasPreviousPeriod = previousTotalSessions > 0
    const cell = (
        <span className="whitespace-nowrap" tabIndex={hasPreviousPeriod ? 0 : undefined}>
            <span className="tabular-nums">{formatNumber(sessions)}</span>
            {totalSessions > 0 ? (
                <span className="text-secondary tabular-nums">
                    {` · ${formatPercentage((sessions / totalSessions) * 100, { compact: true })}`}
                </span>
            ) : null}
        </span>
    )
    if (!hasPreviousPeriod) {
        return cell
    }
    const previousShare = formatPercentage((previousSessions / previousTotalSessions) * 100, { compact: true })
    return <Tooltip title={`Was ${previousShare} of sessions in the previous period`}>{cell}</Tooltip>
}
