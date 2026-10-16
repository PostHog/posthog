import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { watchPicksLogic } from './watchPicksLogic'
import { watchPicksStarterLogic } from './watchPicksStarterLogic'

describe('watchPicksStarterLogic', () => {
    it('moves a chip choice to the confirm step with the loaded recordings as the burst candidates', async () => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/watch_feed/': () => [200, { results: [] }],
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
        const picks = watchPicksLogic({ logicKey: 'starter-test', playlistLogicProps })
        picks.mount()
        const logic = watchPicksStarterLogic(picks.props)
        logic.mount()
        await expectLogic(logic, () => logic.actions.chooseTemplate('dead_end')).toFinishAllListeners()
        expect(logic.values.templateKey).toBe('dead_end')
        expect(logic.values.template?.name).toBe('Dead ends')
        expect(logic.values.spendMode).toBe('free')
        expect(logic.values.candidateRecordings).toEqual(playlist.values.sessionRecordings)
    })
})
