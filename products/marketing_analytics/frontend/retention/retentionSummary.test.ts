import { MarketingAnalyticsRetentionSummaryRow } from '~/queries/schema/schema-general'

import { pairWithPrevious, returnRate } from './retentionSummary'

describe('retentionSummary', () => {
    const row = (breakdownValue: string, previous = false): MarketingAnalyticsRetentionSummaryRow => ({
        breakdownValue,
        previous,
        acquired: 10,
        returners: 2,
        eligible7d: 5,
        returned7d: 0,
        eligible30d: 0,
        returned30d: 0,
        medianReturnDays: 4,
    })

    it('pairs interleaved periods by breakdown and keeps new breakdowns', () => {
        const email = row('Email')
        const previousEmail = row('Email', true)
        const direct = row('Direct')
        expect(pairWithPrevious([row('Organic', true), email, previousEmail, direct])).toEqual([
            { ...email, comparison: previousEmail },
            { ...direct, comparison: undefined },
        ])
    })

    it('distinguishes a zero return rate from a cohort with no eligible visitors', () => {
        expect(returnRate(row('Email'), 7)).toBe(0)
        expect(returnRate(row('Email'), 30)).toBeNull()
        expect(returnRate(undefined, 7)).toBeNull()
    })
})
