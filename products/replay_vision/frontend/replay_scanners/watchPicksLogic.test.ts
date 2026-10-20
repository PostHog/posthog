import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { picksInListFromFlag } from './picksInList'
import { emptyImpressionsStorageKey, picksShownCountStorageKey, watchPicksLogic } from './watchPicksLogic'

describe('watchPicksLogic', () => {
    let feedSpy: jest.Mock
    let viewedSpy: jest.Mock
    const playlistLogicProps = { logicKey: 'test-picks' }

    const item = (id: string, sessionId: string, keyMomentMs?: number): Record<string, any> => ({
        observation: {
            id,
            scanner_id: 'scanner-a',
            session_id: sessionId,
            status: 'succeeded',
            viewed: false,
            scanner_result: keyMomentMs === undefined ? null : { model_output: { key_moment_ms: keyMomentMs } },
        },
        reason: { kind: 'signal_emitted' },
    })

    beforeEach(() => {
        feedSpy = jest.fn(() => [
            200,
            { results: [item('o1', 'session-a', 45000), item('o2', 'session-a'), item('o3', 'session-b')] },
        ])
        viewedSpy = jest.fn(() => [200, {}])
        useMocks({
            get: { '/api/projects/:team/vision/scanners/watch_feed/': feedSpy },
            post: { '/api/projects/:team/vision/observations/:id/viewed/': viewedSpy },
        })
        localStorage.clear()
        initKeaTests()
    })

    it.each([
        ['in-list', true],
        ['control', false],
        ['watch-tab', false],
        ['both', false],
        [undefined, false],
    ])('maps flag value %p to picks in the list: %p', (flagValue, expected) => {
        expect(picksInListFromFlag(flagValue)).toBe(expected)
    })

    describe('inside a recordings list', () => {
        let logic: ReturnType<typeof watchPicksLogic.build>
        let playlistLogic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>
        let captureSpy: jest.SpyInstance

        const mountList = async (): Promise<void> => {
            captureSpy = jest.spyOn(posthog, 'capture').mockImplementation()
            captureSpy.mockClear()
            playlistLogic = sessionRecordingsPlaylistLogic(playlistLogicProps)
            playlistLogic.mount()
            logic = watchPicksLogic({ logicKey: 'test-picks', playlistLogicProps })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadPicks']).toFinishAllListeners()
        }

        beforeEach(async () => {
            router.actions.push('/replay/home')
            await mountList()
        })

        afterEach(() => {
            logic.unmount()
            playlistLogic.unmount()
        })

        it('loads a bounded window, keeps every moment, and does not select anything', () => {
            const url = new URL(feedSpy.mock.calls[0][0].request.url)
            expect(url.searchParams.get('date_from')).toBe('-7d')
            expect(url.searchParams.get('limit')).toBe('50')
            expect(logic.values.picks?.map((pick) => pick.observation.id)).toEqual(['o1', 'o2', 'o3'])
            expect(playlistLogic.values.selectedRecordingId).toBeNull()
        })

        const shownEvents = (): unknown[] =>
            captureSpy.mock.calls.filter(([name]) => name === 'replay_vision_watch_picks_shown').map((call) => call[1])

        it('opens on the picks and reports the impression with its count', () => {
            expect(logic.values.effectiveListMode).toBe('picks')
            expect(shownEvents()).toEqual([
                expect.objectContaining({
                    view: 'list',
                    count: 3,
                    unwatched_count: 3,
                    shown_count: 1,
                    feed_load_id: logic.values.picksLoad?.feedLoadId,
                    observation_ids: ['o1', 'o2', 'o3'],
                }),
            ])
        })

        it('reports impressions of served picks only, not of the unranked fallback rows', () => {
            const [served] = logic.values.picks ?? []
            logic.actions.cardSeen(served as any, 0)
            logic.actions.cardSeen(item('fallback', 'session-c') as any, 0)
            logic.unmount()
            const batches = captureSpy.mock.calls
                .filter(([name]) => name === 'replay_vision_watch_feed_impressions')
                .map(([, props]) => props.impressions.map((i: { observation_id: string }) => i.observation_id))
            expect(batches).toEqual([['o1']])
            logic.mount()
        })

        it.each([
            [1, []],
            [2, [{ view: 'list' }]],
            [3, []],
        ])('reports the third impression as its own event (stored count %i)', async (stored, thirdTimeEvents) => {
            logic.unmount()
            playlistLogic.unmount()
            localStorage.setItem(picksShownCountStorageKey(), String(stored))
            await mountList()
            expect(
                captureSpy.mock.calls
                    .filter(([name]) => name === 'replay_vision_watch_picks_shown_third_time')
                    .map((call) => call[1])
            ).toEqual(thirdTimeEvents)
            expect(localStorage.getItem(picksShownCountStorageKey())).toBe(String(stored + 1))
        })

        it.each([
            ['recordings', {}],
            ['picks', { sessionRecordingId: 'session-a' }],
        ])('remembers %s across mounts, even over a deep link', async (mode, params) => {
            logic.actions.setListMode(mode as 'recordings' | 'picks')
            logic.unmount()
            playlistLogic.unmount()
            router.actions.push('/replay/home', params)
            await mountList()
            expect(logic.values.effectiveListMode).toBe(mode)
        })

        it.each([
            [0, 'picks', '1'],
            [1, 'picks', '2'],
            [2, 'recordings', '2'],
        ])(
            'opens an empty feed on the picks until %i untouched impressions, then on the recordings',
            async (stored, mode, storedAfter) => {
                logic.unmount()
                playlistLogic.unmount()
                feedSpy.mockImplementation(() => [200, { results: [] }])
                localStorage.setItem(emptyImpressionsStorageKey(), String(stored))
                await mountList()
                expect(logic.values.effectiveListMode).toBe(mode)
                expect(localStorage.getItem(emptyImpressionsStorageKey())).toBe(storedAfter)
                expect(shownEvents()).toEqual([])
            }
        )

        it('starting a scanner from the column keeps the picks open and forgets the empty impressions', async () => {
            localStorage.setItem(emptyImpressionsStorageKey(), '2')
            logic.actions.setListMode('recordings')
            logic.actions.adoptPicksMode()
            expect(logic.values.effectiveListMode).toBe('picks')
            expect(localStorage.getItem(emptyImpressionsStorageKey())).toBe('0')
        })

        it.each([
            ['the feed fails', () => feedSpy.mockImplementation(() => [500, {}]), {}],
            ['the link carries filters', () => {}, { filters: { date_from: '-30d' } }],
            ['the link carries a saved filter', () => {}, { savedFilterId: 'sf-1' }],
        ])('opens on the recordings when %s', async (_, arrange, params) => {
            logic.unmount()
            playlistLogic.unmount()
            arrange()
            router.actions.push('/replay/home', params)
            await mountList()
            expect(logic.values.effectiveListMode).toBe('recordings')
            expect(shownEvents()).toEqual([])
        })

        it('selects the pick, seeks ahead of its key moment, and marks it viewed for this person', async () => {
            expect(logic.values.unwatchedCount).toBe(3)
            await expectLogic(logic, () => {
                logic.actions.watchPick(logic.values.picks![0], 0)
            })
                .toDispatchActions([playlistLogic.actionCreators.setSelectedRecordingId('session-a')])
                .toFinishAllListeners()
            expect(router.values.searchParams).toMatchObject({ t: 42, sidebarTab: 'observations' })
            expect(logic.values.activeSessionId).toBe('session-a')
            expect(logic.values.picks![0].observation.viewed).toBe(true)
            expect(logic.values.unwatchedCount).toBe(2)
            expect(viewedSpy).toHaveBeenCalledTimes(1)
            expect(viewedSpy.mock.calls[0][0].request.url).toContain('/vision/observations/o1/viewed/')
        })
    })
})
