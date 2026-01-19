import { initKeaTests } from '~/test/init'

import { virtualizedLogsListLogic } from './virtualizedLogsListLogic'

describe('virtualizedLogsListLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    describe('shouldLoadMore', () => {
        it.each([
            // [stopIndex, dataLength, hasMore, isLoading, expected, description]
            [50, 200, true, false, false, 'not close to end'],
            [100, 200, true, false, true, 'exactly at threshold'],
            [150, 200, true, false, true, 'past threshold'],
            [199, 200, true, false, true, 'at very end'],
            [150, 200, false, false, false, 'no more to load'],
            [150, 200, true, true, false, 'already loading'],
        ])(
            'stopIndex=%i, dataLength=%i, hasMore=%s, isLoading=%s → %s (%s)',
            (stopIndex, dataLength, hasMore, isLoading, expected) => {
                const logic = virtualizedLogsListLogic({ tabId: 'test-tab' })
                logic.mount()

                expect(logic.values.shouldLoadMore(stopIndex, dataLength, hasMore, isLoading)).toBe(expected)
            }
        )

        it('respects custom scrollThreshold', () => {
            const logic = virtualizedLogsListLogic({ tabId: 'test-tab', scrollThreshold: 50 })
            logic.mount()

            // With threshold 50: dataLength 200 - 50 = 150, so stopIndex 149 should NOT load
            expect(logic.values.shouldLoadMore(149, 200, true, false)).toBe(false)
            // But stopIndex 150 should load
            expect(logic.values.shouldLoadMore(150, 200, true, false)).toBe(true)
        })
    })
})
