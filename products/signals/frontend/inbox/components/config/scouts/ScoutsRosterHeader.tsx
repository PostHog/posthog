import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scratchpadLogic } from '../../../logics/scratchpadLogic'
import { SCOUT_ROSTER_WINDOW_LABEL } from '../../../utils/scoutRunsWindow'
import { ScoutsRosterFilters } from './ScoutsRosterFilters'

function Stat({ value, label, alert = false }: { value: string; label: string; alert?: boolean }): JSX.Element {
    return (
        <div className="flex flex-col border-r border-primary pr-4 last:border-r-0">
            <span className={cn('text-lg font-semibold tabular-nums leading-tight', alert && 'text-danger')}>
                {value}
            </span>
            <span className="text-[11px] text-muted">{label}</span>
        </div>
    )
}

/**
 * Headline numbers on the left, search and the tag filter pushed right on the same line. They were
 * two stacked rows before, which burned a whole row of height at every width — `ml-auto` keeps the
 * search right-aligned, and the row only wraps once the two halves genuinely can't share a line.
 */
export function ScoutsRosterHeader(): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-6 pt-4 pb-3">
            <RosterStats />
            <ScoutsRosterFilters />
        </div>
    )
}

/**
 * The troop's headline numbers. Output is stated as reports filed rather than as a run success
 * rate: every run completing tells you nothing crashed, not that the troop is earning its keep.
 */
function RosterStats(): JSX.Element {
    const { rosterGroupCounts, enabledCount, emittedFindingsSummary, fleetFindingsSummaryLoadedOnce } =
        useValues(scoutFleetLogic)
    // Mounted here rather than by the fleet logic, so the 1,000-entry scratchpad read only happens
    // on the surfaces that show it, not on every inbox tab that mounts the fleet.
    const { recentlyLearnedCount, entries: scratchpadEntries } = useValues(scratchpadLogic)
    // A summary that hasn't landed is not zero runs. The number holds a dash until it does; a failed
    // request keeps the dash rather than claiming a quiet week.
    const summaryValue = (value: number): string => (fleetFindingsSummaryLoadedOnce ? String(value) : '—')

    return (
        <div className="flex flex-wrap items-center gap-4">
            {rosterGroupCounts.needs_you > 0 && (
                <Stat value={String(rosterGroupCounts.needs_you)} label="need you" alert />
            )}
            <Stat value={String(enabledCount)} label="on patrol" />
            <Tooltip title={`Runs your scouts made in the ${SCOUT_ROSTER_WINDOW_LABEL}, quiet ones included.`}>
                <span>
                    <Stat value={summaryValue(emittedFindingsSummary.runCount)} label="runs" />
                </span>
            </Tooltip>
            <Tooltip title={`New reports your scouts filed in the ${SCOUT_ROSTER_WINDOW_LABEL}.`}>
                <span>
                    <Stat value={summaryValue(emittedFindingsSummary.authoredReportCount)} label="reports filed" />
                </span>
            </Tooltip>
            <Tooltip title={`Existing reports your scouts added to in the ${SCOUT_ROSTER_WINDOW_LABEL}.`}>
                <span>
                    <Stat value={summaryValue(emittedFindingsSummary.editedReportCount)} label="reports edited" />
                </span>
            </Tooltip>
            <Tooltip title={`Scratchpad entries your scouts wrote or refreshed in the ${SCOUT_ROSTER_WINDOW_LABEL}.`}>
                <span>
                    <Stat value={scratchpadEntries === null ? '—' : String(recentlyLearnedCount)} label="learned" />
                </span>
            </Tooltip>
        </div>
    )
}
