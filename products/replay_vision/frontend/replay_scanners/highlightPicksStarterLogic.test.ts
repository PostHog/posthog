import { router } from 'kea-router'

import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { highlightPicksLogic } from './highlightPicksLogic'
import { highlightPicksStarterLogic } from './highlightPicksStarterLogic'

describe('highlightPicksStarterLogic', () => {
    it('plans the burst from the loaded recordings and starts on free credits', () => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/highlight_feed/': () => [200, { results: [] }],
                '/api/environments/:team/vision/quota/': () => [
                    200,
                    { free_monthly_credits: 2500, credits_used: 0, credit_limit: null },
                ],
            },
        })
        initKeaTests()
        router.actions.push('/replay/home')
        const playlistLogicProps = { logicKey: 'starter-test' }
        const playlist = sessionRecordingsPlaylistLogic(playlistLogicProps)
        playlist.mount()
        const picks = highlightPicksLogic({ logicKey: 'starter-test', playlistLogicProps })
        picks.mount()
        const logic = highlightPicksStarterLogic(picks.props)
        logic.mount()
        expect(logic.values.spendMode).toBe('free')
        expect(logic.values.candidateRecordings).toEqual(playlist.values.sessionRecordings)
    })
})
