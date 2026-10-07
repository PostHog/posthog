import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { watchPicksLogic } from './watchPicksLogic'
import { watchPicksVariantFromFlag } from './watchPicksVariant'

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
        initKeaTests()
    })

    it.each([
        ['in-list', 'in-list'],
        ['watch-tab', 'watch-tab'],
        ['both', 'both'],
        ['control', null],
        [undefined, null],
    ])('maps flag value %p to variant %p', (flagValue, variant) => {
        expect(watchPicksVariantFromFlag(flagValue)).toBe(variant)
    })

    describe('inside a recordings list', () => {
        let logic: ReturnType<typeof watchPicksLogic.build>
        let playlistLogic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>

        beforeEach(async () => {
            playlistLogic = sessionRecordingsPlaylistLogic(playlistLogicProps)
            playlistLogic.mount()
            logic = watchPicksLogic({ logicKey: 'test-picks', playlistLogicProps })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadPicks', 'loadPicksSuccess']).toFinishAllListeners()
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

        it('selects the pick, seeks ahead of its key moment, and marks it viewed for this person', async () => {
            expect(logic.values.unwatchedCount).toBe(3)
            await expectLogic(logic, () => {
                logic.actions.watchPick(logic.values.picks![0], 0, 'list')
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

    describe('on the What to watch page', () => {
        let logic: ReturnType<typeof watchPicksLogic.build>

        beforeEach(async () => {
            logic = watchPicksLogic({ logicKey: 'test-page' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadPicksSuccess']).toFinishAllListeners()
        })

        afterEach(() => {
            logic.unmount()
        })

        it.each([
            ['with a key moment', 0, 'session-a', 42],
            ['without one', 2, 'session-b', undefined],
        ])('opens the pick on the Recordings tab %s', async (_, index, sessionId, t) => {
            await expectLogic(logic, () => {
                logic.actions.watchPick(logic.values.picks![index], index, 'top_10')
            }).toFinishAllListeners()
            expect(router.values.location.pathname).toMatch(/\/replay\/home$/)
            expect(router.values.searchParams).toMatchObject({
                sessionRecordingId: sessionId,
                sidebarTab: 'observations',
                showInspector: true,
            })
            expect(router.values.searchParams.t).toBe(t)
        })
    })
})
