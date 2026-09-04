import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { _LogsImpactResponseApi } from 'products/logs/frontend/generated/api.schemas'

export interface LogsImpactCountsProps {
    impact: _LogsImpactResponseApi
}

/**
 * Sessions and users behind a set of logs, with how much of the set carries each ID.
 * The coverage figure is load-bearing: a session count over 3% of the logs means
 * something different from the same count over all of them.
 */
export function LogsImpactCounts({ impact }: LogsImpactCountsProps): JSX.Element | null {
    if (impact.total === 0) {
        return null
    }

    if (impact.logsWithSessionId === 0 && impact.logsWithDistinctId === 0) {
        return (
            <Tooltip title="No logs in this view carry a session ID or a person distinct ID. Add one to your log attributes to see the sessions and users behind them.">
                <span className="text-muted text-xs" data-attr="logs-impact-no-coverage">
                    No session or user IDs
                </span>
            </Tooltip>
        )
    }

    const percentOfLogs = (count: number): string => {
        const percent = Math.round((count / impact.total) * 100)
        // A count only renders when it is above zero, so a rounded 0% would contradict it.
        return percent === 0 ? '<1%' : `${percent}%`
    }

    return (
        <span className="flex items-center gap-2 text-muted text-xs" data-attr="logs-impact-counts">
            {impact.logsWithSessionId > 0 && (
                <Tooltip
                    title={`Estimated unique session IDs on the matching logs. ${percentOfLogs(
                        impact.logsWithSessionId
                    )} of them carry a session ID.`}
                >
                    <span data-attr="logs-impact-sessions">{humanFriendlyLargeNumber(impact.sessions)} sessions</span>
                </Tooltip>
            )}
            {impact.logsWithDistinctId > 0 && (
                <Tooltip
                    title={`Estimated unique people on the matching logs. ${percentOfLogs(
                        impact.logsWithDistinctId
                    )} of them carry a distinct ID.`}
                >
                    <span data-attr="logs-impact-users">{humanFriendlyLargeNumber(impact.users)} users</span>
                </Tooltip>
            )}
        </span>
    )
}
