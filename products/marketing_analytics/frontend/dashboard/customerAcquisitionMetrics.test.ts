import { WebOverviewItem } from '~/queries/schema/schema-general'

import { customerAcquisitionMetrics } from './customerAcquisitionMetrics'

describe('customerAcquisitionMetrics', () => {
    it.each([
        ['normal', 2, 10, 1, 10, 20, 10, 100],
        ['over 100%', 3, 1, 1, 1, 300, 100, 200],
        ['zero visitors', 2, 0, 1, 10, undefined, 10, undefined],
        ['missing visitors', 2, undefined, 1, undefined, undefined, undefined, undefined],
        ['comparison off', 2, 10, undefined, undefined, 20, undefined, undefined],
        ['zero prior visitors', 2, 10, 1, 0, 20, undefined, undefined],
        ['zero baseline', 2, 10, 0, 10, 20, 0, undefined],
        ['zero customers', 0, 10, 1, 10, 0, 10, -100],
        ['missing customers value', undefined, 10, undefined, 10, undefined, undefined, undefined],
    ] as const)('%s', (_, count, visitors, priorCount, priorVisitors, value, previous, change) => {
        const customers: WebOverviewItem = {
            key: 'unique conversions',
            kind: 'unit',
            value: count,
            previous: priorCount,
            isIncreaseBad: false,
        }
        const rate: WebOverviewItem = {
            key: 'conversion rate',
            kind: 'percentage',
            value: 99,
            previous: 99,
            changeFromPreviousPct: 999,
            isIncreaseBad: false,
        }
        const traffic: WebOverviewItem = {
            key: 'visitors',
            kind: 'unit',
            value: visitors,
            previous: priorVisitors,
        }
        const result = customerAcquisitionMetrics([rate, customers], [traffic])
        expect(result[0]).toBe(customers)
        expect(result[1]).toEqual({ ...rate, value, previous, changeFromPreviousPct: change })
        expect(rate.value).toBe(99)
    })

    it('handles missing responses and missing visitors item', () => {
        expect(customerAcquisitionMetrics(undefined, undefined)).toEqual([])
        const customers: WebOverviewItem = {
            key: 'unique conversions',
            kind: 'unit',
            value: 3,
        }
        for (const traffic of [undefined, []]) {
            expect(customerAcquisitionMetrics([customers], traffic)).toEqual([
                customers,
                {
                    key: 'conversion rate',
                    kind: 'percentage',
                    value: undefined,
                    previous: undefined,
                    changeFromPreviousPct: undefined,
                },
            ])
        }
    })
})
