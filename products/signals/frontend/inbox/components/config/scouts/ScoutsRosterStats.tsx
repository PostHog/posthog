import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scratchpadLogic } from '../../../logics/scratchpadLogic'
import { SCOUT_ROSTER_WINDOW_LABEL } from '../../../utils/scoutRunsWindow'

type StatTone = 'muted' | 'warning' | 'danger'

const VALUE_CLASS: Record<StatTone, string> = {
    muted: 'text-default',
    warning: 'text-warning',
    danger: 'text-danger',
}

const LABEL_CLASS: Record<StatTone, string> = {
    muted: 'text-muted',
    warning: 'text-warning',
    danger: 'text-danger',
}

function Stat({
    value,
    label,
    tooltip,
    tone = 'muted',
}: {
    value: string
    label: string
    tooltip: string
    tone?: StatTone
}): JSX.Element {
    return (
        <Tooltip title={tooltip}>
            <span className={cn('flex items-baseline gap-1 whitespace-nowrap text-xs', LABEL_CLASS[tone])}>
                <span className={cn('font-semibold tabular-nums', VALUE_CLASS[tone])}>{value}</span>
                <span>{label}</span>
            </span>
        </Tooltip>
    )
}

/**
 * The troop's headline numbers, inline on the toolbar. Output is stated as reports filed rather than
 * as a run success rate: every run completing tells you nothing crashed, not that the troop is
 * earning its keep.
 */
export function ScoutsRosterStats(): JSX.Element {
    const { pauseAttentionCounts, enabledCount, emittedFindingsSummary, fleetFindingsSummaryLoadedOnce } =
        useValues(scoutFleetLogic)
    // Mounted here rather than by the fleet logic, so the 1,000-entry scratchpad read only happens
    // on the surfaces that show it, not on every inbox tab that mounts the fleet.
    const { recentlyLearnedCount, recentlyLearnedCountCapped, entries: scratchpadEntries } = useValues(scratchpadLogic)
    // A summary that hasn't landed is not zero runs. The number holds a dash until it does; a failed
    // request keeps the dash rather than claiming a quiet week.
    const summaryValue = (value: number): string => (fleetFindingsSummaryLoadedOnce ? String(value) : '—')
    const learnedValue =
        scratchpadEntries === null ? '—' : `${recentlyLearnedCount}${recentlyLearnedCountCapped ? '+' : ''}`

    return (
        <div className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1" data-attr="inbox-scout-stats">
            {pauseAttentionCounts.pausingSoon > 0 && (
                <Stat
                    value={String(pauseAttentionCounts.pausingSoon)}
                    label="pausing soon"
                    tone="warning"
                    tooltip="Scouts that will pause themselves because nobody acted on their reports. They still run. Open one to keep it going."
                />
            )}
            {pauseAttentionCounts.recentlyPaused > 0 && (
                <Stat
                    value={String(pauseAttentionCounts.recentlyPaused)}
                    label="recently paused"
                    tone="danger"
                    tooltip="Scouts that paused themselves: their runs kept failing, nobody acted on their reports, or they surfaced nothing. Open one to turn it back on."
                />
            )}
            <Stat
                value={String(enabledCount)}
                label="on patrol"
                tooltip="Scouts that are turned on and run on their schedule, dry runs included."
            />
            <Stat
                value={summaryValue(emittedFindingsSummary.runCount)}
                label="runs"
                tooltip={`Runs your scouts made in the ${SCOUT_ROSTER_WINDOW_LABEL}, quiet ones included.`}
            />
            <Stat
                value={summaryValue(emittedFindingsSummary.authoredReportCount)}
                label="reports filed"
                tooltip={`New reports your scouts filed in the ${SCOUT_ROSTER_WINDOW_LABEL}.`}
            />
            <Stat
                value={summaryValue(emittedFindingsSummary.editedReportCount)}
                label="reports edited"
                tooltip={`Existing reports your scouts added to in the ${SCOUT_ROSTER_WINDOW_LABEL}.`}
            />
            <Stat
                value={learnedValue}
                label="learned"
                tooltip={
                    recentlyLearnedCountCapped
                        ? `Scratchpad entries your scouts wrote or refreshed in the ${SCOUT_ROSTER_WINDOW_LABEL}. Only the newest 1,000 entries are counted, and all of them fall in this window.`
                        : `Scratchpad entries your scouts wrote or refreshed in the ${SCOUT_ROSTER_WINDOW_LABEL}.`
                }
            />
        </div>
    )
}
