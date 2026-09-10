import { Tooltip } from '@posthog/lemon-ui'

import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'

import { ScoutCostRollup, scoutCostWindowLabel } from '../../../utils/scoutCosts'
import { ScoutRosterRow } from '../../../utils/scoutGroups'
import { formatRunCost } from '../../../utils/scoutRunsWindow'

type CostRate = { unit: 'day' | 'run' | 'report'; of: (rollup: ScoutCostRollup) => number | null; title: string }

const COST_RATES: CostRate[] = [
    { unit: 'day', of: (rollup) => rollup.perDay, title: 'Spend over the window, divided by its days.' },
    { unit: 'run', of: (rollup) => rollup.perRun, title: 'Spend over the runs that had spend attributed.' },
    {
        unit: 'report',
        of: (rollup) => rollup.perReport,
        title: 'Spend over the reports the scout filed or added to. Blank when it produced none.',
    },
]

function ScoutCostCell({ value }: { value: number | null }): JSX.Element {
    if (value === null) {
        // The scout spent, but produced no report to price. A dash says that without claiming $0.00.
        return <span className="text-xs text-muted">&ndash;</span>
    }
    // The header carries the unit, so the cell is the money alone.
    return <span className="text-xs text-secondary tabular-nums">{formatRunCost(value)}</span>
}

/**
 * The three cost columns for the roster table, staff only. Sorting by `$/day` answers which scouts
 * the spend is in, and by `$/report` which are expensive for what they produce. A scout with no
 * priced run in the window has no rollup, so its cells stay blank.
 */
export function scoutCostColumns(
    rollups: Map<string, ScoutCostRollup>,
    windowDays: number
): LemonTableColumn<ScoutRosterRow, keyof ScoutRosterRow | undefined>[] {
    return COST_RATES.map(({ unit, of, title }) => ({
        title: (
            <Tooltip title={`${title} Over the ${scoutCostWindowLabel(windowDays)}.`}>
                <span>${`/${unit}`}</span>
            </Tooltip>
        ),
        key: `cost-per-${unit}`,
        width: '7%',
        align: 'right' as const,
        sorter: (a: ScoutRosterRow, b: ScoutRosterRow) => sortValue(rollups, a, of) - sortValue(rollups, b, of),
        render: (_: any, row: ScoutRosterRow) => {
            const rollup = rollups.get(row.config.skill_name)
            return rollup ? <ScoutCostCell value={of(rollup)} /> : <span />
        },
    }))
}

// A scout without a number sorts below every scout that has one, so sorting a column descending
// puts the biggest spenders on top and the unpriced ones out of the way.
function sortValue(
    rollups: Map<string, ScoutCostRollup>,
    row: ScoutRosterRow,
    of: (rollup: ScoutCostRollup) => number | null
): number {
    const rollup = rollups.get(row.config.skill_name)
    return (rollup ? of(rollup) : null) ?? Number.NEGATIVE_INFINITY
}
