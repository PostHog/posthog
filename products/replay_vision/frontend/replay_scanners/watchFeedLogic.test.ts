import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { watchFeedLogic } from './watchFeedLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({ lemonToast: { success: jest.fn(), error: jest.fn() } }))

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

    beforeEach(() => {
        feedSpy = jest.fn(() => [200, { results: [item('o1', 'signal_emitted'), item('o2', 'recent')] }])
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
        const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation()
        const lastFeedViewed = (): Record<string, any> | null | undefined =>
            captureSpy.mock.calls.filter(([name]) => name === 'replay_vision_watch_feed_viewed').at(-1)?.[1]
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFeed', 'loadFeedSuccess']).toFinishAllListeners()
        expect(logic.values.feedItems).toHaveLength(2)
        expect(new URL(feedSpy.mock.calls[0][0].request.url).searchParams.get('date_from')).toBe('-7d')
        // A response without a ranker (an older API) reads as the default arm, outside the experiment.
        expect(logic.values.feedRanker).toBe('weighted-score')
        expect(lastFeedViewed()).not.toHaveProperty('$feature/vision-watch-feed-ranker')

        feedSpy.mockImplementation(() => [
            200,
            { results: [item('o1', 'jev_watchable')], ranker: 'jev', ranker_variant: 'jev' },
        ])
        await expectLogic(logic, () => {
            logic.actions.setScannerTypeFilter('monitor')
        })
            .toDispatchActions(['loadFeed', 'loadFeedSuccess'])
            .toFinishAllListeners()
        const lastUrl = new URL(feedSpy.mock.calls.at(-1)[0].request.url)
        expect(lastUrl.searchParams.get('scanner_type')).toBe('monitor')
        // The response names the ranker that ordered the feed, and the feed-viewed event reports the
        // project's variant, which is the exposure the experiment counts.
        expect(logic.values.feedRanker).toBe('jev')
        expect(lastFeedViewed()).toMatchObject({ ranker: 'jev', '$feature/vision-watch-feed-ranker': 'jev' })

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
            logic.actions.setCreatedByFilter(['7', '12'])
        })
            .toDispatchActions(['loadFeedSuccess'])
            .toFinishAllListeners()
        params = new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams
        expect(params.get('created_by')).toBe('7,12')

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
            logic.actions.setCreatedByFilter(['7'])
        })
            .toDispatchActions(['loadFeedSuccess'])
            .toFinishAllListeners()

        // A link that names only tags is a full snapshot: tags apply and the remembered scanner and creator
        // clear, in a single load, so the same link shows the same feed to every recipient.
        await expectLogic(logic, () => {
            router.actions.push('/replay-vision?feed_tags=checkout')
        })
            .toDispatchActions(['restoreFeedFilters', 'loadFeed', 'loadFeedSuccess'])
            .toFinishAllListeners()
        expect(logic.values.tagsFilter).toEqual(['checkout'])
        expect(logic.values.scannerIdsFilter).toEqual([])
        expect(logic.values.createdByFilter).toEqual([])
        const params = new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams
        expect(params.get('tags')).toBe('checkout')
        expect(params.get('scanner_ids')).toBeNull()
        expect(params.get('created_by')).toBeNull()
    })

    it('clears every filter at once', async () => {
        logic.mount()
        logic.actions.setScannerIdsFilter(['scanner-a'])
        logic.actions.setTagsFilter(['checkout'])
        logic.actions.setCreatedByFilter(['7'])
        await expectLogic(logic, () => {
            logic.actions.clearFeedFilters()
        })
            .toMatchValues({
                scannerIdsFilter: [],
                tagsFilter: [],
                createdByFilter: [],
                search: '',
                hasFeedFilters: false,
            })
            .toFinishAllListeners()
    })

    it('names the empty reason only once the fleet and budget have answered', async () => {
        feedSpy.mockImplementation(() => [200, { results: [] }])
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': () => [
                    200,
                    { results: [{ id: 'scanner-a', enabled: false, limit_reached: false }], next: null },
                ],
                '/api/projects/:team/vision/quota/': () => [200, { exhausted: false }],
            },
        })
        logic.mount()
        // A reader with scanners must never be shown the no-scanners screen while the list is in flight.
        expect(logic.values.emptyReason).toBeNull()

        await expectLogic(logic).toDispatchActions(['loadFeedSuccess']).toFinishAllListeners()
        expect(logic.values.emptyReason).toBe('all-disabled')
    })

    it('puts a card back when hiding fails, and leaves a reloaded feed alone on a late restore', async () => {
        let dismissStatus = 500
        useMocks({
            post: { '/api/projects/:team/vision/observations/:id/feed_dismissal/': () => [dismissStatus] },
            delete: { '/api/projects/:team/vision/observations/:id/feed_dismissal/': () => [204] },
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFeedSuccess']).toFinishAllListeners()
        const [first] = logic.values.feedItems ?? []

        await expectLogic(logic, () => logic.actions.dismissItem(first, 0, null)).toFinishAllListeners()
        expect(logic.values.feedItems?.map((i) => i.observation.id)).toEqual(['o1', 'o2'])

        dismissStatus = 204
        await expectLogic(logic, () => logic.actions.dismissItem(first, 0, 'already_known')).toFinishAllListeners()
        expect(logic.values.feedItems?.map((i) => i.observation.id)).toEqual(['o2'])

        feedSpy.mockImplementation(() => [200, { results: [item('o3', 'recent')] }])
        await expectLogic(logic, () => logic.actions.setScannerTypeFilter('monitor')).toFinishAllListeners()
        const undo = jest.mocked(lemonToast.success).mock.calls.at(-1)?.[1]?.button?.action
        expect(undo).toBeTruthy()
        await undo?.()
        expect(jest.mocked(lemonToast.error)).toHaveBeenCalledTimes(1)
        expect(logic.values.feedItems?.map((i) => i.observation.id)).toEqual(['o3'])
    })

    it('flags a failed load and clears the flag on retry', async () => {
        feedSpy.mockImplementation(() => [500, { detail: 'nope' }])
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadFeed', 'loadFeedFailure'])
            .toMatchValues({ feedFailed: true, feedItems: null })
        feedSpy.mockImplementation(() => [200, { results: [] }])
        await expectLogic(logic, () => {
            logic.actions.loadFeed()
        })
            .toDispatchActions(['loadFeedSuccess'])
            .toMatchValues({ feedFailed: false, feedItems: [] })
    })
})
