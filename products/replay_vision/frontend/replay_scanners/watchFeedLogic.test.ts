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
        feedSpy.mockImplementation(() => [200, { results: [] }])
        await expectLogic(logic, () => {
            logic.actions.loadFeed()
        })
            .toDispatchActions(['loadFeedSuccess'])
            .toMatchValues({ feedFailed: false, feedItems: [] })
    })
})
