import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { initKeaTests } from '~/test/init'

import { homeTabDataCollectionId } from './homeTabQueryKeys'
import { homeTabReloadLogic } from './homeTabReloadLogic'

describe('homeTabReloadLogic', () => {
    let logic: ReturnType<typeof homeTabReloadLogic.build>
    let collection: ReturnType<typeof dataNodeCollectionLogic.build>

    const loadTile = (id: string, minutesAgo: number | 'failed'): void => {
        collection.actions.mountDataNode(id, { id, loadData: jest.fn(), cancelQuery: jest.fn() })
        collection.actions.collectionNodeLoadData(id)
        if (minutesAgo === 'failed') {
            collection.actions.collectionNodeLoadDataFailure(id)
            return
        }
        collection.actions.collectionNodeLoadDataSuccess(id, {
            lastRefresh: new Date(Date.now() - minutesAgo * 60_000).toISOString(),
        })
    }

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-01-15T12:00:00Z'))
        initKeaTests()
        collection = dataNodeCollectionLogic({ key: homeTabDataCollectionId(123) })
        collection.mount()
        logic = homeTabReloadLogic({ teamId: 123 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        collection.unmount()
        jest.useRealTimers()
    })

    test.each<[string, (number | 'failed')[], boolean]>([
        ['every result is recent', [1, 2], true],
        ['every result is older than the interval', [6, 7], false],
        ['the oldest result is older than the interval', [1, 6], false],
        ['a tile failed and the other results are recent', [1, 'failed'], false],
    ])('blocks a reload when %s', (_case, minutesAgo, blocked) => {
        minutesAgo.forEach((minutes, index) => loadTile(`tile-${index}`, minutes))

        expect(logic.values.reloadDisabledReason?.startsWith('Next reload possible') ?? false).toBe(blocked)
    })

    it('allows a reload again when the interval ends', () => {
        loadTile('tile', 1)
        expect(logic.values.reloadDisabledReason).toMatch(/^Next reload possible/)

        jest.advanceTimersByTime(4 * 60_000)

        expect(logic.values.reloadDisabledReason).toBeNull()
    })
})
