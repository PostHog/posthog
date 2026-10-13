import { getNextSorting } from 'lib/lemon-ui/LemonTable/sorting'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { computeScoutCostRollups } from '../../../utils/scoutCosts'
import { ScoutRosterRow } from '../../../utils/scoutGroups'
import { scoutCostColumns } from './ScoutCostCell'

function row(skillName: string): ScoutRosterRow {
    return { config: { skill_name: skillName } as SignalScoutConfig, group: 'working' }
}

describe('scoutCostColumns', () => {
    // `unpriced` had runs but nothing attributed, so it gets no rollup and none of the three rates.
    const rollups = computeScoutCostRollups({
        window_days: 7,
        available: true,
        scouts: [
            { skill_name: 'cheap', spend_usd: 0.7, run_count: 7, priced_run_count: 7, reports_touched: 7 },
            { skill_name: 'unpriced', spend_usd: 0, run_count: 3, priced_run_count: 0, reports_touched: 0 },
            { skill_name: 'pricey', spend_usd: 7, run_count: 7, priced_run_count: 7, reports_touched: 7 },
        ],
    })
    const rows = [row('cheap'), row('unpriced'), row('pricey')]

    it.each(['cost-per-day', 'cost-per-run', 'cost-per-report'])(
        'sorts the biggest spender first and the scout with no number last on a first click of %s',
        (key) => {
            const column = scoutCostColumns(rollups, 7).find((candidate) => candidate.key === key)!
            // The order the table itself lands on for an unsorted column, so a change to either
            // the column's default or the table's fails here.
            const { order } = getNextSorting(null, key, false, column.defaultSortOrder)!
            const sorter = column.sorter as (a: ScoutRosterRow, b: ScoutRosterRow) => number

            const sorted = rows.slice().sort((a, b) => order * sorter(a, b))

            expect(sorted.map((sortedRow) => sortedRow.config.skill_name)).toEqual(['pricey', 'cheap', 'unpriced'])
        }
    )
})
