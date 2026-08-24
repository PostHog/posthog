import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scratchpadLogic } from '../../../logics/scratchpadLogic'
import { SCOUT_ROSTER_WINDOW_LABEL } from '../../../utils/scoutRunsWindow'

function Stat({
    value,
    label,
    alert = false,
    tooltip,
}: {
    value: string
    label: string
    alert?: boolean
    tooltip?: string
}): JSX.Element {
    const stat = (
        <span
            className={cn('flex items-baseline gap-1 whitespace-nowrap text-xs', alert ? 'text-danger' : 'text-muted')}
        >
            <span className={cn('font-semibold tabular-nums', alert ? 'text-danger' : 'text-default')}>{value}</span>
            <span>{label}</span>
        </span>
    )
    return tooltip ? (
        <Tooltip title={tooltip}>
            <span>{stat}</span>
        </Tooltip>
    ) : (
        stat
    )
}

/**
 * The troop's headline numbers, inline on the toolbar. Output is stated as reports filed rather than
 * as a run success rate: every run completing tells you nothing crashed, not that the troop is
 * earning its keep.
 */
export function ScoutsRosterStats(): JSX.Element {
    const { rosterGroupCounts, enabledCount, emittedFindingsSummary, fleetFindingsSummaryLoadedOnce } =
        useValues(scoutFleetLogic)
    // Mounted here rather than by the fleet logic, so the 1,000-entry scratchpad read only happens
    // on the surfaces that show it, not on every inbox tab that mounts the fleet.
    const { recentlyLearnedCount, entries: scratchpadEntries } = useValues(scratchpadLogic)
    // A summary that hasn't landed is not zero runs. The number holds a dash until it does; a failed
    // request keeps the dash rather than claiming a quiet week.
    const summaryValue = (value: number): string => (fleetFindingsSummaryLoadedOnce ? String(value) : '—')

    return (
        <div className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1" data-attr="inbox-scout-stats">
            {rosterGroupCounts.needs_you > 0 && (
                <Stat value={String(rosterGroupCounts.needs_you)} label="need you" alert />
            )}
            <Stat value={String(enabledCount)} label="on patrol" />
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
                value={scratchpadEntries === null ? '—' : String(recentlyLearnedCount)}
                label="learned"
                tooltip={`Scratchpad entries your scouts wrote or refreshed in the ${SCOUT_ROSTER_WINDOW_LABEL}.`}
            />
        </div>
    )
}
