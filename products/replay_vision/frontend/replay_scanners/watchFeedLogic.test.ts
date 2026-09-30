import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { watchFeedLogic } from './watchFeedLogic'

describe('watchFeedLogic', () => {
    let logic: ReturnType<typeof watchFeedLogic.build>
    let feedSpy: jest.Mock

    const item = (id: string, reasonKind: string): Record<string, any> => ({
        observation: {
            id,
            scanner_id: 'scanner-a',
            session_id: `session-${id}`,
            status: 'succeeded',
            created_at: '2026-05-12T00:00:00Z',
        },
        reason: { kind: reasonKind },
    })

    const page = (results: Record<string, any>[], hasMore: boolean, nextOffset: number): Record<string, any> => ({
        results,
        has_more: hasMore,
        next_offset: nextOffset,
        date_from: '2026-05-05T00:00:00+00:00',
        date_to: '2026-05-12T00:00:00+00:00',
    })

    beforeEach(() => {
        feedSpy = jest.fn(() => [200, page([item('o1', 'signal_emitted'), item('o2', 'recent')], false, 2)])
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/watch_feed/': feedSpy,
            },
        })
        initKeaTests()
        logic = watchFeedLogic.build()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads on mount and reloads with params when filters change', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFeed', 'loadFeedSuccess']).toFinishAllListeners()
        expect(logic.values.feedItems).toHaveLength(2)
        expect(new URL(feedSpy.mock.calls[0][0].request.url).searchParams.get('date_from')).toBe('-7d')

        await expectLogic(logic, () => {
            logic.actions.setScannerTypeFilter('monitor')
        })
            .toDispatchActions(['loadFeed', 'loadFeedSuccess'])
            .toFinishAllListeners()
        const lastUrl = new URL(feedSpy.mock.calls.at(-1)[0].request.url)
        expect(lastUrl.searchParams.get('scanner_type')).toBe('monitor')

        await expectLogic(logic, () => {
            logic.actions.setDateRange('-30d', null)
        })
            .toDispatchActions(['loadFeed', 'loadFeedSuccess'])
            .toFinishAllListeners()
        expect(new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams.get('date_from')).toBe('-30d')
    })

    it('sends scanner, tag and search filters, and keeps persisted picks on a filterless URL', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFeedSuccess']).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setScannerIdsFilter(['scanner-a', 'scanner-b'])
        })
            .toDispatchActions(['loadFeedSuccess'])
            .toFinishAllListeners()
        let params = new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams
        expect(params.get('scanner_ids')).toBe('scanner-a,scanner-b')

        await expectLogic(logic, () => {
            logic.actions.setTagsFilter(['checkout'])
        })
            .toDispatchActions(['loadFeedSuccess'])
            .toFinishAllListeners()
        params = new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams
        expect(params.get('tags')).toBe('checkout')

        await expectLogic(logic, () => {
            logic.actions.setSearch('  coupon  ')
        })
            .toDispatchActions(['loadFeedSuccess'])
            .toFinishAllListeners()
        expect(new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams.get('search')).toBe('coupon')

        // A URL with no feed params must not silently widen the reader's feed back to every scanner.
        await expectLogic(logic, () => {
            router.actions.push('/replay-vision')
        }).toFinishAllListeners()
        expect(logic.values.scannerIdsFilter).toEqual(['scanner-a', 'scanner-b'])
    })

    it('restores a shared link as a full snapshot, clearing filters it omits', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFeedSuccess']).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setScannerIdsFilter(['scanner-a'])
        })
            .toDispatchActions(['loadFeedSuccess'])
            .toFinishAllListeners()

        // A link that names only tags is a full snapshot: tags apply and the remembered scanner clears,
        // in a single load, so the same link shows the same feed to every recipient.
        await expectLogic(logic, () => {
            router.actions.push('/replay-vision?feed_tags=checkout')
        })
            .toDispatchActions(['restoreFeedFilters', 'loadFeed', 'loadFeedSuccess'])
            .toFinishAllListeners()
        expect(logic.values.tagsFilter).toEqual(['checkout'])
        expect(logic.values.scannerIdsFilter).toEqual([])
        const params = new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams
        expect(params.get('tags')).toBe('checkout')
        expect(params.get('scanner_ids')).toBeNull()
    })

    it('clears every filter at once', async () => {
        logic.mount()
        logic.actions.setScannerIdsFilter(['scanner-a'])
        logic.actions.setTagsFilter(['checkout'])
        await expectLogic(logic, () => {
            logic.actions.clearFeedFilters()
        })
            .toMatchValues({ scannerIdsFilter: [], tagsFilter: [], search: '', hasFeedFilters: false })
            .toFinishAllListeners()
    })

    it('flags a failed load and clears the flag on retry', async () => {
        feedSpy.mockImplementation(() => [500, { detail: 'nope' }])
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadFeed', 'loadFeedFailure'])
            .toMatchValues({ feedFailed: true, feedItems: null })
        feedSpy.mockImplementation(() => [200, page([], false, 0)])
        await expectLogic(logic, () => {
            logic.actions.loadFeed()
        })
            .toDispatchActions(['loadFeedSuccess'])
            .toMatchValues({ feedFailed: false, feedItems: [] })
    })

    it('pages deeper with the pinned window and appends without duplicates', async () => {
        feedSpy.mockImplementation((req: any) => {
            const offset = new URL(req.request.url).searchParams.get('offset')
            return offset
                ? // o2 comes back again: its viewed state changed between pages and re-ranked it across
                  // the boundary, which the append must absorb rather than show the card twice.
                  [200, page([item('o2', 'recent'), item('o3', 'friction')], false, 4)]
                : [200, page([item('o1', 'signal_emitted'), item('o2', 'recent')], true, 2)]
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFeedSuccess']).toFinishAllListeners()
        expect(logic.values.feedPage).toEqual({
            hasMore: true,
            nextOffset: 2,
            dateFrom: '2026-05-05T00:00:00+00:00',
            dateTo: '2026-05-12T00:00:00+00:00',
        })

        await expectLogic(logic, () => {
            logic.actions.loadMoreFeed()
        })
            .toDispatchActions(['loadMoreFeed', 'loadMoreFeedSuccess'])
            .toFinishAllListeners()
        const params = new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams
        expect(params.get('offset')).toBe('2')
        expect(params.get('date_from')).toBe('2026-05-05T00:00:00+00:00')
        expect(params.get('date_to')).toBe('2026-05-12T00:00:00+00:00')
        expect((logic.values.feedItems ?? []).map((i) => i.observation.id)).toEqual(['o1', 'o2', 'o3'])
        expect(logic.values.feedPage?.hasMore).toBe(false)
    })

    it('a filter change resets paging and requests a fresh unpinned window', async () => {
        feedSpy.mockImplementation((req: any) => {
            const offset = new URL(req.request.url).searchParams.get('offset')
            return offset
                ? [200, page([item('o3', 'friction')], false, 4)]
                : [200, page([item('o1', 'signal_emitted'), item('o2', 'recent')], true, 2)]
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFeedSuccess']).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.loadMoreFeed()
        })
            .toDispatchActions(['loadMoreFeedSuccess'])
            .toFinishAllListeners()
        expect(logic.values.feedItems).toHaveLength(3)

        await expectLogic(logic, () => {
            logic.actions.setScannerTypeFilter('monitor')
        })
            .toDispatchActions(['loadFeed', 'loadFeedSuccess'])
            .toFinishAllListeners()
        const params = new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams
        expect(params.get('offset')).toBeNull()
        expect(params.get('date_from')).toBe('-7d')
        expect(logic.values.feedItems).toHaveLength(2)
        expect(logic.values.feedPage?.hasMore).toBe(true)
    })

    it('a failed page keeps the feed and stops the sentinel until retried', async () => {
        feedSpy.mockImplementation((req: any) => {
            const offset = new URL(req.request.url).searchParams.get('offset')
            return offset
                ? [500, { detail: 'nope' }]
                : [200, page([item('o1', 'signal_emitted'), item('o2', 'recent')], true, 2)]
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFeedSuccess']).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.loadMoreFeed()
        })
            .toDispatchActions(['loadMoreFeed', 'loadMoreFeedFailure'])
            .toFinishAllListeners()
        expect(logic.values.feedItems).toHaveLength(2)
        expect(logic.values.loadMoreFailed).toBe(true)
        expect(logic.values.feedFailed).toBe(false)
        expect(logic.values.loadingMore).toBe(false)
    })
})
