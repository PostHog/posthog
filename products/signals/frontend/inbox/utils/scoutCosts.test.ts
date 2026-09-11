import type { ScoutCostApi, ScoutCostsApi } from 'products/signals/frontend/generated/api.schemas'

import { computeScoutCostRollups, scoutCostLineParts } from './scoutCosts'

function costs(scouts: Partial<ScoutCostApi>[], overrides: Partial<ScoutCostsApi> = {}): ScoutCostsApi {
    return {
        window_days: 7,
        available: true,
        scouts: scouts.map((scout, index) => ({
            skill_name: `signals-scout-${index}`,
            spend_usd: 0,
            run_count: 0,
            priced_run_count: 0,
            reports_touched: 0,
            ...scout,
        })),
        ...overrides,
    }
}

describe('scoutCosts', () => {
    describe('computeScoutCostRollups', () => {
        it('divides spend by the window, by the priced runs, and by the reports touched', () => {
            const rollups = computeScoutCostRollups(
                costs([{ skill_name: 'a', spend_usd: 1.68, run_count: 14, priced_run_count: 12, reports_touched: 11 }])
            )

            const rollup = rollups.get('a')
            expect(rollup?.perDay).toBeCloseTo(0.24)
            // Runs with nothing attributed are not free runs, so they stay out of the divisor.
            expect(rollup?.perRun).toBeCloseTo(0.14)
            expect(rollup?.perReport).toBeCloseTo(0.1527)
        })

        it('leaves cost per report unset when the scout produced nothing, rather than pricing it at zero', () => {
            const rollups = computeScoutCostRollups(
                costs([{ skill_name: 'a', spend_usd: 13.02, run_count: 6, priced_run_count: 6, reports_touched: 0 }])
            )

            expect(rollups.get('a')?.perReport).toBeNull()
            expect(rollups.get('a')?.perDay).toBeCloseTo(1.86)
        })

        it.each<[string, Partial<ScoutCostApi>[], Partial<ScoutCostsApi>]>([
            // Nothing was attributed, so the spend is unknown, not zero: every surface omits it.
            ['no priced run in the window', [{ skill_name: 'a', run_count: 3, priced_run_count: 0 }], {}],
            [
                'no internal project to read spend from',
                [{ skill_name: 'a', spend_usd: 1.5, run_count: 3, priced_run_count: 3 }],
                { available: false },
            ],
        ])('has no rollup when there is %s', (_name, scouts, overrides) => {
            expect(computeScoutCostRollups(costs(scouts, overrides)).size).toEqual(0)
        })

        it('has no rollup before the read lands', () => {
            expect(computeScoutCostRollups(null).size).toEqual(0)
        })
    })

    describe('scoutCostLineParts', () => {
        it.each<[string, Partial<ScoutCostApi>, string]>([
            [
                'the three rates',
                { spend_usd: 1.68, run_count: 14, priced_run_count: 14, reports_touched: 11 },
                '$0.24/day · $0.12/run · $0.15/report',
            ],
            [
                'the spend and no report to price',
                { spend_usd: 13.02, run_count: 6, priced_run_count: 6, reports_touched: 0 },
                '$1.86/day · $2.17/run · no reports',
            ],
            [
                // A sub-cent rate at two decimals would read as "$0.00", which says the scout is free.
                'four decimals on a sub-cent rate',
                { spend_usd: 0.014, run_count: 2, priced_run_count: 2, reports_touched: 2 },
                '$0.0020/day · $0.0070/run · $0.0070/report',
            ],
        ])('renders %s', (_name, scout, expected) => {
            const rollup = computeScoutCostRollups(costs([{ skill_name: 'a', ...scout }])).get('a')!
            expect(scoutCostLineParts(rollup).join(' · ')).toEqual(expected)
        })
    })
})
