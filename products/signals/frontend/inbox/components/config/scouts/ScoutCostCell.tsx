import { Tooltip } from '@posthog/lemon-ui'

import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'

import { ScoutCostRollup, scoutCostWindowLabel } from '../../../utils/scoutCosts'
import { ScoutRosterRow } from '../../../utils/scoutGroups'
import { formatRunCost } from '../../../utils/scoutRunsWindow'

type CostRate = { unit: 'day' | 'run' | 'report'; of: (rollup: ScoutCostRollup) => number | null; tooltip: string }

const COST_RATES: CostRate[] = [
    { unit: 'day', of: (rollup) => rollup.perDay, tooltip: 'Spend over the window, divided by its days.' },
    { unit: 'run', of: (rollup) => rollup.perRun, tooltip: 'Spend over the runs that had spend attributed.' },
    {
        unit: 'report',
        of: (rollup) => rollup.perReport,
        tooltip: 'Spend over the reports the scout filed or added to. Blank when it produced none.',
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
    return COST_RATES.map(({ unit, of, tooltip }) => ({
        title: (
            <Tooltip title={`${tooltip} Over the ${scoutCostWindowLabel(windowDays)}.`}>
                <span>{`$/${unit}`}</span>
            </Tooltip>
        ),
        key: `cost-per-${unit}`,
        width: '7%',
        align: 'right' as const,
        // Descending first, so one click answers the question the column exists for: the biggest
        // spenders on top, the scouts with no number out of the way at the bottom. Ascending would
        // open with a block of blank cells.
        defaultSortOrder: -1 as const,
        sorter: (a: ScoutRosterRow, b: ScoutRosterRow) => {
            const left = sortValue(rollups, a, of)
            const right = sortValue(rollups, b, of)
            // Two rows without a number are equal, and subtracting one infinity from the other
            // would hand the table a NaN.
            return left === right ? 0 : left - right
        },
        render: (_: any, row: ScoutRosterRow) => {
            const rollup = rollups.get(row.config.skill_name)
            return rollup ? <ScoutCostCell value={of(rollup)} /> : <span />
        },
    }))
}

// A scout without a number sorts below every scout that has one in the descending direction, which
// is the direction a first click takes. Sorting ascending asks for the cheapest first, and lifts
// the unpriced scouts with it.
function sortValue(
    rollups: Map<string, ScoutCostRollup>,
    row: ScoutRosterRow,
    of: (rollup: ScoutCostRollup) => number | null
): number {
    const rollup = rollups.get(row.config.skill_name)
    return (rollup ? of(rollup) : null) ?? Number.NEGATIVE_INFINITY
}
