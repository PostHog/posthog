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
 * Sessions and people behind a set of spans. The coverage figure is load-bearing: a session
 * count over 3% of the spans means something different from the same count over all of them.
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

    return (
        <span className="flex items-center gap-1 text-muted text-xs" data-attr="tracing-impact-counts">
            <ImpactCount
                count={impact.sessions}
                coveredSpans={impact.spansWithSessionId}
                totalSpans={impact.total}
                noun="sessions"
                caption="Estimated unique session IDs, by span count."
                coverageNoun="a session ID"
                entries={impact.topSessions ?? []}
                dataAttr="tracing-impact-sessions"
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
            <ImpactCount
                count={impact.users}
                coveredSpans={impact.spansWithDistinctId}
                totalSpans={impact.total}
                noun="users"
                caption="Estimated unique people, by span count."
                coverageNoun="a distinct ID"
                entries={impact.topUsers ?? []}
                dataAttr="tracing-impact-users"
                renderValue={(value) => (
                    <span onClick={(e) => e.stopPropagation()}>
                        <PersonDisplay person={{ distinct_id: value }} noEllipsis inline />
                    </span>
                )}
            />
        </span>
    )
}

interface ImpactCountProps {
    count: number
    coveredSpans: number
    totalSpans: number
    noun: string
    caption: string
    coverageNoun: string
    entries: _TracingImpactTopValueApi[]
    dataAttr: string
    renderValue: (value: string) => JSX.Element
}

/** One count, with the coverage it was estimated over and a popover of the values behind it. */
function ImpactCount({
    count,
    coveredSpans,
    totalSpans,
    noun,
    caption,
    coverageNoun,
    entries,
    dataAttr,
    renderValue,
}: ImpactCountProps): JSX.Element | null {
    if (coveredSpans === 0) {
        return null
    }

    const fullCaption = `${caption} ${formatIdentityCoverage(
        coveredSpans,
        totalSpans
    )} of the matching spans carry ${coverageNoun}.`

    return (
        <LemonDropdown
            placement="bottom-start"
            closeOnClickInside={false}
            overlay={
                <div className="flex flex-col gap-1 p-1 max-w-160">
                    <span className="text-muted text-xs">{fullCaption}</span>
                    {entries.map(({ value, count: spanCount }) => (
                        <div key={value} className="flex items-center justify-between gap-4 text-xs">
                            <span className="font-mono truncate">{renderValue(value)}</span>
                            <span className="text-muted whitespace-nowrap">
                                <span>{humanFriendlyLargeNumber(spanCount)}</span> spans
                            </span>
                        </div>
                    ))}
                </div>
            }
        >
            <LemonButton size="xsmall" data-attr={dataAttr} tooltip={fullCaption}>
                <span className="text-muted text-xs font-normal">
                    {/* The changing number gets its own element: a bare changing text node beside
                    siblings breaks under in-page translation. */}
                    <span>{humanFriendlyLargeNumber(count)}</span> {noun}
                </span>
            </LemonButton>
        </LemonDropdown>
    )
}
