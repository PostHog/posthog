import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { initKeaTests } from '~/test/init'

import { homeTabLoadTimeLogic } from './homeTabLoadTimeLogic'
import { homeTabDataCollectionId } from './homeTabQueryKeys'

jest.mock('posthog-js')

describe('homeTabLoadTimeLogic', () => {
    let logic: ReturnType<typeof homeTabLoadTimeLogic.build>
    let collection: ReturnType<typeof dataNodeCollectionLogic.build>
    let now: number

    const loadEvents = (): Record<string, unknown>[] =>
        (posthog.capture as jest.Mock).mock.calls
            .filter(([event]) => event === 'product_analytics_home_load')
            .map(([, properties]) => properties)

    beforeEach(() => {
        initKeaTests()
        ;(posthog.capture as jest.Mock).mockClear()
        now = 100
        jest.spyOn(performance, 'now').mockImplementation(() => now)
        collection = dataNodeCollectionLogic({ key: homeTabDataCollectionId(123) })
        collection.mount()
        logic = homeTabLoadTimeLogic({ teamId: 123, tileIds: ['a', 'b'], defaultDateRange: true, compare: true })
        logic.mount()
    })

    afterEach(() => {
        if (logic.isMounted()) {
            logic.unmount()
        }
        collection.unmount()
        jest.restoreAllMocks()
    })

    it.each(['success', 'failure'] as const)('waits for all visible tiles and reports %s once', async (status) => {
        collection.actions.collectionNodeLoadData('a')
        collection.actions.collectionNodeLoadData('b')
        collection.actions.collectionNodeLoadData('hidden-chart')
        collection.actions.collectionNodeLoadDataSuccess('a')
        await expectLogic(logic).toFinishAllListeners()
        expect(loadEvents()).toHaveLength(0)

        now = 350
        if (status === 'success') {
            collection.actions.collectionNodeLoadDataSuccess('b', { isCached: true })
        } else {
            collection.actions.collectionNodeLoadDataFailure('b')
        }
        await expectLogic(logic).toFinishAllListeners()

        expect(loadEvents()).toEqual([
            expect.objectContaining({
                team_id: 123,
                duration_ms: 250,
                status,
                load_type: 'query',
                tile_count: 2,
                failed_tile_count: status === 'failure' ? 1 : 0,
                was_hidden: false,
                default_date_range: true,
                compare: true,
            }),
        ])
        const [, mounted] = (posthog.capture as jest.Mock).mock.calls.find(
            ([event]) => event === 'product_analytics_home_mounted'
        )
        expect(loadEvents()[0].visit_id).toBe(mounted.visit_id)

        collection.actions.collectionNodeLoadDataSuccess('hidden-chart')
        collection.actions.collectionNodeLoadData('a')
        collection.actions.collectionNodeLoadDataSuccess('a')
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
        expect(loadEvents()).toHaveLength(1)
    })

    it('measures a new cached visit without waiting for a query', async () => {
        collection.actions.collectionNodeLoadData('a')
        collection.actions.collectionNodeLoadData('b')
        collection.actions.collectionNodeLoadDataSuccess('a')
        collection.actions.collectionNodeLoadDataSuccess('b')
        await expectLogic(logic).toFinishAllListeners()
        const initialVisit = loadEvents()[0].visit_id
        logic.unmount()
        ;(posthog.capture as jest.Mock).mockClear()

        now = 500
        logic.mount()
        now = 510
        await expectLogic(logic).toFinishAllListeners()

        expect(loadEvents()).toEqual([
            expect.objectContaining({ status: 'success', load_type: 'cached', duration_ms: 10 }),
        ])
        expect(loadEvents()[0].visit_id).not.toBe(initialVisit)
    })

    it.each(['navigation', 'pagehide'] as const)('reports an unfinished visit on %s', async (exit) => {
        collection.actions.collectionNodeLoadData('a')
        await expectLogic(logic).toFinishAllListeners()
        now = 600
        if (exit === 'pagehide') {
            collection.actions.pageHidden()
        }
        logic.unmount()

        expect(loadEvents()).toEqual([
            expect.objectContaining({ status: 'cancelled', load_type: 'query', duration_ms: 500 }),
        ])
    })

    it('waits for queries that still run when the tab opens again', async () => {
        collection.actions.collectionNodeLoadData('a')
        collection.actions.collectionNodeLoadData('b')
        logic.unmount()
        ;(posthog.capture as jest.Mock).mockClear()
        logic.mount()
        collection.actions.collectionNodeLoadDataSuccess('a')
        await expectLogic(logic).toFinishAllListeners()
        expect(loadEvents()).toHaveLength(0)
        collection.actions.collectionNodeLoadDataSuccess('b')
        await expectLogic(logic).toFinishAllListeners()
        expect(loadEvents()).toEqual([expect.objectContaining({ status: 'success', load_type: 'query' })])
    })

    it('marks hidden visits and ignores load results from another project', async () => {
        const other = dataNodeCollectionLogic({ key: homeTabDataCollectionId(456) })
        other.mount()
        other.actions.collectionNodeLoadData('a')
        other.actions.collectionNodeLoadDataSuccess('a')
        other.actions.collectionNodeLoadData('b')
        other.actions.collectionNodeLoadDataSuccess('b')
        await expectLogic(logic).toFinishAllListeners()
        expect(loadEvents()).toHaveLength(0)
        other.unmount()

        collection.actions.collectionNodeLoadData('a')
        collection.actions.collectionNodeLoadData('b')
        collection.actions.visibilityChanged(true)
        collection.actions.visibilityChanged(false)
        collection.actions.collectionNodeLoadDataSuccess('a')
        collection.actions.collectionNodeLoadDataSuccess('b')
        await expectLogic(logic).toFinishAllListeners()
        expect(loadEvents()).toEqual([expect.objectContaining({ team_id: 123, was_hidden: true })])
    })
})
