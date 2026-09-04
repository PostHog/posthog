import { LemonButton, LemonDropdown, Tooltip } from '@posthog/lemon-ui'

import ViewRecordingButton, {
    RecordingPlayerType,
    ViewRecordingButtonVariant,
} from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { humanFriendlyLargeNumber, percentage } from 'lib/utils/numbers'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import type { _LogsImpactResponseApi, _LogsImpactTopValueApi } from 'products/logs/frontend/generated/api.schemas'

export interface LogsImpactCountsProps {
    impact: _LogsImpactResponseApi
    /** Pivots the viewer to Group mode grouped by the dominant session ID key. */
    onGroupBySessions?: () => void
}

/**
 * Sessions and users behind a set of logs, with how much of the set carries each ID.
 * The coverage figure is load-bearing: a session count over 3% of the logs means
 * something different from the same count over all of them. Each count opens a
 * popover with the top values behind it, linking into replay and person profiles.
 */
export function LogsImpactCounts({ impact, onGroupBySessions }: LogsImpactCountsProps): JSX.Element | null {
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
        const fraction = count / impact.total
        // Rounding must not contradict the visible counts: partial coverage never reads
        // as a flat 0% or 100%.
        if (fraction < 0.005) {
            return '<1%'
        }
        if (fraction > 0.995 && fraction < 1) {
            return '>99%'
        }
        return percentage(fraction, 0)
    }

    return (
        <span className="flex items-center gap-1 text-muted text-xs" data-attr="logs-impact-counts">
            {impact.logsWithSessionId > 0 && (
                <LemonDropdown
                    placement="bottom-start"
                    closeOnClickInside={false}
                    overlay={
                        <TopValuesOverlay
                            caption={`Estimated unique session IDs, by log count. ${percentOfLogs(
                                impact.logsWithSessionId
                            )} of the matching logs carry a session ID.`}
                            entries={impact.topSessions}
                            renderValue={(value) => (
                                <ViewRecordingButton
                                    sessionId={value}
                                    openPlayerIn={RecordingPlayerType.Modal}
                                    label={value}
                                    variant={ViewRecordingButtonVariant.Link}
                                    checkRecordingExists
                                    data-attr="logs-impact-top-session"
                                />
                            )}
                            action={
                                onGroupBySessions && (
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        fullWidth
                                        center
                                        onClick={onGroupBySessions}
                                        data-attr="logs-impact-group-by-sessions"
                                    >
                                        Group logs by session ID
                                    </LemonButton>
                                )
                            }
                        />
                    }
                >
                    <LemonButton size="xsmall" data-attr="logs-impact-sessions">
                        <span className="text-muted text-xs font-normal">
                            {humanFriendlyLargeNumber(impact.sessions)} sessions
                        </span>
                    </LemonButton>
                </LemonDropdown>
            )}
            {impact.logsWithDistinctId > 0 && (
                <LemonDropdown
                    placement="bottom-start"
                    closeOnClickInside={false}
                    overlay={
                        <TopValuesOverlay
                            caption={`Estimated unique people, by log count. ${percentOfLogs(
                                impact.logsWithDistinctId
                            )} of the matching logs carry a distinct ID.`}
                            entries={impact.topUsers}
                            renderValue={(value) => (
                                <span onClick={(e) => e.stopPropagation()}>
                                    <PersonDisplay person={{ distinct_id: value }} noEllipsis inline />
                                </span>
                            )}
                        />
                    }
                >
                    <LemonButton size="xsmall" data-attr="logs-impact-users">
                        <span className="text-muted text-xs font-normal">
                            {humanFriendlyLargeNumber(impact.users)} users
                        </span>
                    </LemonButton>
                </LemonDropdown>
            )}
        </span>
    )
}

interface TopValuesOverlayProps {
    caption: string
    entries: _LogsImpactTopValueApi[]
    renderValue: (value: string) => JSX.Element
    action?: React.ReactNode
}

/** Top identity values behind one impact count, each with its approximate log count. */
function TopValuesOverlay({ caption, entries, renderValue, action }: TopValuesOverlayProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1 p-1 max-w-160">
            <span className="text-muted text-xs">{caption}</span>
            {entries.map(({ value, count }) => (
                <div key={value} className="flex items-center justify-between gap-4 text-xs">
                    <span className="font-mono truncate">{renderValue(value)}</span>
                    <span className="text-muted whitespace-nowrap">{humanFriendlyLargeNumber(count)} logs</span>
                </div>
            ))}
            {action}
        </div>
    )
}
