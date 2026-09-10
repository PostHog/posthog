import { LemonButton, LemonDropdown, Tooltip } from '@posthog/lemon-ui'

import ViewRecordingButton, {
    RecordingPlayerType,
    ViewRecordingButtonVariant,
} from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import type {
    _TracingImpactResponseApi,
    _TracingImpactTopValueApi,
} from 'products/tracing/frontend/generated/api.schemas'

import { formatIdentityCoverage } from '../identityCoverage'

export interface TracingImpactCountsProps {
    impact: _TracingImpactResponseApi
}

/**
 * Sessions and people behind a set of spans, with how much of the set carries each ID.
 * The coverage figure is load-bearing: a session count over 3% of the spans means something
 * different from the same count over all of them. Each count opens a popover with the top
 * values behind it, linking into replay and person profiles.
 */
export function TracingImpactCounts({ impact }: TracingImpactCountsProps): JSX.Element | null {
    if (impact.total === 0) {
        return null
    }

    if (impact.spansWithSessionId === 0 && impact.spansWithDistinctId === 0) {
        return (
            <Tooltip title="No spans in this view carry a session ID or a person distinct ID. Add one to your span attributes to see the sessions and people behind them.">
                <span className="text-muted text-xs" data-attr="tracing-impact-no-coverage">
                    No session or user IDs
                </span>
            </Tooltip>
        )
    }

    const sessionsCaption = `Estimated unique session IDs, by span count. ${formatIdentityCoverage(
        impact.spansWithSessionId,
        impact.total
    )} of the matching spans carry a session ID.`
    const usersCaption = `Estimated unique people, by span count. ${formatIdentityCoverage(
        impact.spansWithDistinctId,
        impact.total
    )} of the matching spans carry a distinct ID.`

    return (
        <span className="flex items-center gap-1 text-muted text-xs" data-attr="tracing-impact-counts">
            {impact.spansWithSessionId > 0 && (
                <LemonDropdown
                    placement="bottom-start"
                    closeOnClickInside={false}
                    overlay={
                        <TopValuesOverlay
                            caption={sessionsCaption}
                            entries={impact.topSessions ?? []}
                            renderValue={(value) => (
                                <ViewRecordingButton
                                    sessionId={value}
                                    openPlayerIn={RecordingPlayerType.Modal}
                                    label={value}
                                    variant={ViewRecordingButtonVariant.Link}
                                    checkRecordingExists
                                    data-attr="tracing-impact-top-session"
                                />
                            )}
                        />
                    }
                >
                    <LemonButton size="xsmall" data-attr="tracing-impact-sessions" tooltip={sessionsCaption}>
                        <span className="text-muted text-xs font-normal">
                            {/* The changing number gets its own element: a bare changing text node
                            beside siblings breaks under in-page translation. */}
                            <span>{humanFriendlyLargeNumber(impact.sessions)}</span> sessions
                        </span>
                    </LemonButton>
                </LemonDropdown>
            )}
            {impact.spansWithDistinctId > 0 && (
                <LemonDropdown
                    placement="bottom-start"
                    closeOnClickInside={false}
                    overlay={
                        <TopValuesOverlay
                            caption={usersCaption}
                            entries={impact.topUsers ?? []}
                            renderValue={(value) => (
                                <span onClick={(e) => e.stopPropagation()}>
                                    <PersonDisplay person={{ distinct_id: value }} noEllipsis inline />
                                </span>
                            )}
                        />
                    }
                >
                    <LemonButton size="xsmall" data-attr="tracing-impact-users" tooltip={usersCaption}>
                        <span className="text-muted text-xs font-normal">
                            <span>{humanFriendlyLargeNumber(impact.users)}</span> users
                        </span>
                    </LemonButton>
                </LemonDropdown>
            )}
        </span>
    )
}

interface TopValuesOverlayProps {
    caption: string
    entries: _TracingImpactTopValueApi[]
    renderValue: (value: string) => JSX.Element
}

/** Top identity values behind one impact count, each with its approximate span count. */
function TopValuesOverlay({ caption, entries, renderValue }: TopValuesOverlayProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1 p-1 max-w-160">
            <span className="text-muted text-xs">{caption}</span>
            {entries.map(({ value, count }) => (
                <div key={value} className="flex items-center justify-between gap-4 text-xs">
                    <span className="font-mono truncate">{renderValue(value)}</span>
                    <span className="text-muted whitespace-nowrap">
                        <span>{humanFriendlyLargeNumber(count)}</span> spans
                    </span>
                </div>
            ))}
        </div>
    )
}
