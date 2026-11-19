import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { replayRecordingsLogic } from './replayRecordingsLogic'

describe('replayRecordingsLogic', () => {
    it('probes for recordings once replay is turned on from a page that mounted with it off', async () => {
        useMocks({ get: { '/api/environments/:team/session_recordings/': () => [200, { results: [] }] } })
        initKeaTests()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, session_recording_opt_in: false })
        const logic = replayRecordingsLogic()
        logic.mount()

        await expectLogic(logic).toNotHaveDispatchedActions(['loadHasRecentRecordings'])
        expect(logic.values.recordingsBlock).toBe('replay-off')

        teamLogic.actions.updateCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, session_recording_opt_in: true })

        await expectLogic(logic).toDispatchActions(['loadHasRecentRecordingsSuccess'])
        expect(logic.values.recordingsBlock).toBe('no-recordings')
    })
})
