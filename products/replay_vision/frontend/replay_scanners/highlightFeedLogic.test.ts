import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { visionScannersListLogic } from '../logics/visionScannersListLogic'
import { highlightFeedLogic } from './highlightFeedLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({ lemonToast: { success: jest.fn(), error: jest.fn() } }))

describe('highlightFeedLogic', () => {
    let logic: ReturnType<typeof highlightFeedLogic.build>
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
        // The scope choice persists, so one test's choice must not leak into the next.
        localStorage.clear()
        feedSpy = jest.fn(() => [200, { results: [item('o1', 'embedding_pick'), item('o2', 'recent')] }])
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/highlight_feed/': feedSpy,
                '/api/projects/:team/vision/scanners/': { results: [], next: null },
            },
        })
        initKeaTests()
        logic = highlightFeedLogic.build()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads on mount and reloads with params when filters change', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFeed', 'loadFeedSuccess']).toFinishAllListeners()
        expect(logic.values.feedItems).toHaveLength(2)
        expect(new URL(feedSpy.mock.calls[0][0].request.url).searchParams.get('date_from')).toBe('-7d')

        const owned = [{ id: 'scanner-a', created_by: userLogic.values.user } as unknown as ReplayScannerApi]
        const lastCreatedBy = (): string | null =>
            new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams.get('created_by')
        // The scope tabs are hidden for a viewer with no scanners, so a stored "mine" choice must not narrow the feed.
        const requestsBefore = feedSpy.mock.calls.length
        logic.actions.setOnlyMyScanners(true)
        await expectLogic(logic).toFinishAllListeners()
        expect(feedSpy.mock.calls).toHaveLength(requestsBefore)
        // Owning a scanner applies the stored choice.
        await expectLogic(logic, () => {
            visionScannersListLogic.actions.loadScannersSuccess(owned)
        })
            .toDispatchActions(['loadFeed', 'loadFeedSuccess'])
            .toFinishAllListeners()
        expect(lastCreatedBy()).toBe(String(userLogic.values.user?.id))
        // Losing the last owned scanner drops the scope, and the narrowed feed must reload without it.
        await expectLogic(logic, () => {
            visionScannersListLogic.actions.loadScannersSuccess([])
        })
            .toDispatchActions(['loadFeed', 'loadFeedSuccess'])
            .toFinishAllListeners()
        expect(lastCreatedBy()).toBeNull()
        // A tab switch sends one request, not one per reload path.
        visionScannersListLogic.actions.loadScannersSuccess(owned)
        await expectLogic(logic).toDispatchActions(['loadFeed', 'loadFeedSuccess']).toFinishAllListeners()
        const requestsBeforeSwitch = feedSpy.mock.calls.length
        await expectLogic(logic, () => {
            logic.actions.setOnlyMyScanners(false)
        })
            .toDispatchActions(['loadFeed', 'loadFeedSuccess'])
            .toFinishAllListeners()
        expect(feedSpy.mock.calls).toHaveLength(requestsBeforeSwitch + 1)
        expect(lastCreatedBy()).toBeNull()

        await expectLogic(logic, () => {
            logic.actions.setDateFrom('-30d')
        })
            .toDispatchActions(['loadFeed', 'loadFeedSuccess'])
            .toFinishAllListeners()
        expect(new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams.get('date_from')).toBe('-30d')

        const lastCategories = (): string | null =>
            new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams.get('categories')
        expect(lastCategories()).toBeNull()
        await expectLogic(logic, () => {
            logic.actions.setCategories(['revenue', 'failure'])
        })
            .toDispatchActions(['loadFeed', 'loadFeedSuccess'])
            .toFinishAllListeners()
        expect(lastCategories()).toBe('failure,revenue')
        // Hiding every kind would send an empty filter the server rejects, so the feed shows them all.
        await expectLogic(logic, () => {
            logic.actions.setCategories([])
        })
            .toDispatchActions(['loadFeed', 'loadFeedSuccess'])
            .toFinishAllListeners()
        expect(lastCategories()).toBeNull()
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
        await expectLogic(logic, () => logic.actions.setDateFrom('-30d')).toFinishAllListeners()
        const undo = jest.mocked(lemonToast.success).mock.calls.at(-1)?.[1]?.button?.action
        expect(undo).toBeTruthy()
        await undo?.()
        expect(jest.mocked(lemonToast.error)).toHaveBeenCalledTimes(1)
        expect(logic.values.feedItems?.map((i) => i.observation.id)).toEqual(['o3'])
    })

    it('pages through one load, counting the offset from what was served', async () => {
        useMocks({ post: { '/api/projects/:team/vision/observations/:id/feed_dismissal/': () => [204] } })
        feedSpy.mockImplementation(() => [
            200,
            { results: [item('o1', 'embedding_pick'), item('o2', 'embedding_pick')], has_more: true, as_of: 'T0' },
        ])
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFeedSuccess']).toFinishAllListeners()
        // Hiding a card shortens the list, but the next page still starts after both served cards.
        await expectLogic(logic, () =>
            logic.actions.dismissItem(logic.values.feedItems![0], 0, null)
        ).toFinishAllListeners()

        feedSpy.mockImplementation(() => [
            200,
            { results: [item('o2', 'embedding_pick'), item('o3', 'recent')], has_more: true, as_of: 'T0' },
        ])
        await expectLogic(logic, () => logic.actions.loadMoreFeed({}))
            .toDispatchActions(['loadMoreFeedSuccess'])
            .toFinishAllListeners()

        const pageUrl = new URL(feedSpy.mock.calls.at(-1)[0].request.url)
        expect(pageUrl.searchParams.get('offset')).toBe('2')
        expect(pageUrl.searchParams.get('as_of')).toBe('T0')
        expect(logic.values.feedItems?.map((i) => i.observation.id)).toEqual(['o2', 'o3'])
        expect(logic.values.feedLoad?.positions).toEqual({ o1: 0, o2: 1, o3: 2 })

        // The deduplicated o2 still counts toward the offset, and an empty page ends paging instead of repeating.
        feedSpy.mockImplementation(() => [200, { results: [], has_more: true, as_of: 'T0' }])
        await expectLogic(logic, () => logic.actions.loadMoreFeed({}))
            .toDispatchActions(['loadMoreFeedSuccess'])
            .toFinishAllListeners()

        expect(new URL(feedSpy.mock.calls.at(-1)[0].request.url).searchParams.get('offset')).toBe('4')
        expect(logic.values.feedHasMore).toBe(false)
    })

    it('drops a next page that fails after the filters changed', async () => {
        feedSpy.mockImplementation(() => [
            200,
            { results: [item('o1', 'embedding_pick')], has_more: true, as_of: 'T0' },
        ])
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFeedSuccess']).toFinishAllListeners()

        let failPage: () => void = () => {}
        // The next page (it carries an offset) stays pending until the test fails it; a fresh load answers at once.
        feedSpy.mockImplementation(({ request }) =>
            new URL(request.url).searchParams.has('offset')
                ? new Promise((resolve) => {
                      failPage = () => resolve([500, { detail: 'nope' }])
                  })
                : [200, { results: [item('o2', 'recent')], has_more: true, as_of: 'T1' }]
        )
        logic.actions.loadMoreFeed({})
        // Waiting for every listener would wait on the held page too, so wait for the new load alone.
        await expectLogic(logic, () => logic.actions.setDateFrom('-30d')).toDispatchActions(['loadFeedSuccess'])

        failPage()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.feedMoreFailed).toBe(false)
        expect(logic.values.feedItems?.map((i) => i.observation.id)).toEqual(['o2'])
        expect(logic.values.feedHasMore).toBe(true)
    })

    it('appends a next page once when it is requested again while in flight', async () => {
        feedSpy.mockImplementation(() => [
            200,
            { results: [item('o1', 'embedding_pick')], has_more: true, as_of: 'T0' },
        ])
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFeedSuccess']).toFinishAllListeners()

        const pending: (() => void)[] = []
        feedSpy.mockImplementation(
            () =>
                new Promise((resolve) => {
                    pending.push(() =>
                        resolve([200, { results: [item('o2', 'recent')], has_more: false, as_of: 'T0' }])
                    )
                })
        )
        logic.actions.loadMoreFeed({})
        logic.actions.loadMoreFeed({})
        // Loading the next page keeps the cards usable; only a filter change dims them.
        await expectLogic(logic).toMatchValues({ feedItemsLoading: true, feedReloading: false })
        await waitFor(() => expect(pending).toHaveLength(2))
        // The newer request lands first, then the older one would append the same page again.
        pending[1]()
        await expectLogic(logic).toDispatchActions(['loadMoreFeedSuccess'])
        pending[0]()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.feedItems?.map((i) => i.observation.id)).toEqual(['o1', 'o2'])
    })

    it('flags a failed load and clears the flag on retry', async () => {
        feedSpy.mockImplementation(() => [500, { detail: 'nope' }])
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadFeed', 'loadFeedFailure'])
            .toMatchValues({ feedFailed: true, feedItems: null, feedReloading: false })
        feedSpy.mockImplementation(() => [200, { results: [] }])
        await expectLogic(logic, () => {
            logic.actions.loadFeed()
        })
            .toDispatchActions(['loadFeedSuccess'])
            .toMatchValues({ feedFailed: false, feedItems: [] })
    })
})
