import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { visionScannersListLogic } from '../logics/visionScannersListLogic'
import { highlightPicksLogic } from './highlightPicksLogic'
import { highlightPicksStaleLogic } from './highlightPicksStaleLogic'

describe('highlightPicksStaleLogic', () => {
    it.each([
        ['a quiet window', true, 'startBackfill', 'backfill', 'quiet-window'],
        ['every scanner off', false, 'toggleScanner', 'enable', 'all-disabled'],
    ])(
        'reports an action from the empty state with the empty reason (%s)',
        async (_name, enabled, actionName, action, reason) => {
            useMocks({
                get: {
                    '/api/projects/:team/vision/scanners/highlight_feed/': () => [200, { results: [] }],
                    '/api/projects/:team/vision/scanners/': () => [
                        200,
                        { results: [{ id: 's1', name: 'Quickstart', enabled, limit_reached: false }], next: null },
                    ],
                    '/api/environments/:team/vision/quota/': () => [
                        200,
                        { free_monthly_credits: 2500, credits_used: 0, credit_limit: null },
                    ],
                },
                post: {
                    '/api/projects/:team/vision/scanners/:id/backfills/estimate/': () => [
                        200,
                        { total_sessions: 0, total_credits: 0 },
                    ],
                },
                patch: { '/api/projects/:team/vision/scanners/:id/': () => [200, {}] },
            })
            initKeaTests()
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation()
            const playlistLogicProps = { logicKey: 'stale-test' }
            sessionRecordingsPlaylistLogic(playlistLogicProps).mount()
            const picks = highlightPicksLogic({ logicKey: 'stale-test', playlistLogicProps })
            picks.mount()
            const logic = highlightPicksStaleLogic(picks.props)
            logic.mount()
            await expectLogic(picks).toDispatchActions(['loadPicksSuccess']).toFinishAllListeners()
            await expectLogic(visionScannersListLogic).toFinishAllListeners()
            expect(logic.values.scanners.map((scanner) => scanner.id)).toEqual(['s1'])
            expect(logic.values.staleReason).toBeNull()

            if (actionName === 'startBackfill') {
                logic.actions.startBackfill('s1')
            } else {
                logic.actions.toggleScanner('s1', true)
            }
            await expectLogic(logic).toDispatchActions(['scannerActionDone']).toFinishAllListeners()

            expect(
                captureSpy.mock.calls
                    .filter(([name]) => name === 'replay_vision_highlight_picks_stale_action')
                    .map(([, properties]) => properties)
            ).toEqual([expect.objectContaining({ reason, action, scanner_id: 's1' })])
        }
    )
})
