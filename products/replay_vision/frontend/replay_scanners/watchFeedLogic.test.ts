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
