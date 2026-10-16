import { resetContext } from 'kea'

import { marketingBreakdownTableLogic } from './marketingBreakdownTableLogic'

describe('marketingBreakdownTableLogic', () => {
    it('keeps sorting and cancellation independent for tables with the same default metric', () => {
        resetContext()
        const engagement = marketingBreakdownTableLogic({ tableKey: 'engagement', defaultSortKey: 'sessions' })
        const acquisition = marketingBreakdownTableLogic({ tableKey: 'acquisition', defaultSortKey: 'sessions' })
        const unmountEngagement = engagement.mount()
        const unmountAcquisition = acquisition.mount()

        try {
            engagement.actions.setSorting({ columnKey: 'bounce_rate', order: 1 })
            expect(engagement.values.sorting).toEqual({ columnKey: 'bounce_rate', order: 1 })
            expect(acquisition.values.sorting).toEqual({ columnKey: 'sessions', order: -1 })

            engagement.actions.setSorting(null)
            expect(engagement.values.sorting).toBeNull()
            expect(acquisition.values.sorting).toEqual({ columnKey: 'sessions', order: -1 })
        } finally {
            unmountEngagement()
            unmountAcquisition()
        }
    })
})
