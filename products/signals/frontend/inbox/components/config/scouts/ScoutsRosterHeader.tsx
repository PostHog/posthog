import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scratchpadLogic } from '../../../logics/scratchpadLogic'
import { SCOUT_ROSTER_WINDOW_LABEL } from '../../../utils/scoutRunsWindow'
import { ScoutsRosterFilters } from './ScoutsRosterFilters'

function Stat({ value, label, compact = false }: { value: string; label: string; compact?: boolean }): JSX.Element {
    return (
        <div className={cn('flex flex-col border-r border-primary last:border-r-0', compact ? 'pr-3' : 'pr-4')}>
            <span className="text-lg font-semibold tabular-nums leading-tight">{value}</span>
            <span className="text-[11px] text-muted">{label}</span>
        </div>
    )
}

/**
 * Headline numbers on the left, search and the tag filter pushed right on the same line. They were
 * two stacked rows before, which burned a whole row of height at every width — `ml-auto` keeps the
 * search right-aligned, and the row only wraps once the two halves genuinely can't share a line.
 */
export function ScoutsRosterHeader({ compact }: { compact: boolean }): JSX.Element {
    return (
        <div
            className={cn(
                'flex flex-wrap items-center pt-4 pb-3',
                compact ? 'gap-x-4 gap-y-3 px-4' : 'gap-x-6 gap-y-3 px-6'
            )}
        >
            <RosterStats compact={compact} />
            <ScoutsRosterFilters compact={compact} />
        </div>
    )
}

/**
 * The troop's headline numbers. Output is stated as reports filed rather than as a run success
 * rate: every run completing tells you nothing crashed, not that the troop is earning its keep.
 */
function RosterStats({ compact }: { compact: boolean }): JSX.Element {
    const { enabledCount, emittedFindingsSummary, fleetFindingsSummaryLoadedOnce } = useValues(scoutFleetLogic)
    // Mounted here rather than by the fleet logic, so the 1,000-entry scratchpad read only happens
    // on the surfaces that show it, not on every inbox tab that mounts the fleet.
    const { recentlyLearnedCount, entries: scratchpadEntries } = useValues(scratchpadLogic)
    // A summary that hasn't landed is not zero runs. The number holds a dash until it does; a failed
    // request keeps the dash rather than claiming a quiet week.
    const summaryValue = (value: number): string => (fleetFindingsSummaryLoadedOnce ? String(value) : '—')

    return (
        <div className={cn('flex flex-wrap items-center', compact ? 'gap-x-3 gap-y-2' : 'gap-4')}>
            <Stat value={String(enabledCount)} label="on patrol" compact={compact} />
            <Tooltip title={`Runs your scouts made in the ${SCOUT_ROSTER_WINDOW_LABEL}, quiet ones included.`}>
                <span>
                    <Stat value={summaryValue(emittedFindingsSummary.runCount)} label="runs" compact={compact} />
                </span>
            </Tooltip>
            <Tooltip title={`New reports your scouts filed in the ${SCOUT_ROSTER_WINDOW_LABEL}.`}>
                <span>
                    <Stat
                        value={summaryValue(emittedFindingsSummary.authoredReportCount)}
                        label="reports filed"
                        compact={compact}
                    />
                </span>
            </Tooltip>
            <Tooltip title={`Existing reports your scouts added to in the ${SCOUT_ROSTER_WINDOW_LABEL}.`}>
                <span>
                    <Stat
                        value={summaryValue(emittedFindingsSummary.editedReportCount)}
                        label="reports edited"
                        compact={compact}
                    />
                </span>
            </Tooltip>
            <Tooltip title={`Scratchpad entries your scouts wrote or refreshed in the ${SCOUT_ROSTER_WINDOW_LABEL}.`}>
                <span>
                    <Stat
                        value={scratchpadEntries === null ? '—' : String(recentlyLearnedCount)}
                        label="learned"
                        compact={compact}
                    />
                </span>
            </Tooltip>
        </div>
    )
}
