import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    ObservationStatusEnumApi,
    ReplayObservationApi,
} from 'products/replay_vision/frontend/generated/api.schemas'

import { replayVisionScanWidgetLogic } from './replayVisionScanWidgetLogic'

const SCAN_ID = 'scanner-1'

function observation(sessionId: string, status: ObservationStatusEnumApi): Partial<ReplayObservationApi> {
    return { id: `obs-${sessionId}`, scanner_id: SCAN_ID, session_id: sessionId, status }
}

describe('replayVisionScanWidgetLogic', () => {
    let logic: ReturnType<typeof replayVisionScanWidgetLogic.build>
    let results: Partial<ReplayObservationApi>[]

    beforeEach(() => {
        results = []
        useMocks({
            get: {
                '/api/projects/:team_id/vision/scanners/:scanner_id/observations/': () => [200, { results }],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('counts a session with no row yet as still pending', async () => {
        // The observation row is written moments after the scan starts. Treating an absent row as
        // finished would stop the poll before any result arrived.
        results = [observation('a', 'succeeded')]
        logic = replayVisionScanWidgetLogic({ scanId: SCAN_ID, sessionIds: ['a', 'b'] })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ pendingCount: 1 })
    })

    it('reports nothing pending once every session has a terminal row', async () => {
        results = [observation('a', 'succeeded'), observation('b', 'failed')]
        logic = replayVisionScanWidgetLogic({ scanId: SCAN_ID, sessionIds: ['a', 'b'] })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ pendingCount: 0 })
    })

    it('ignores rows for sessions outside this scan', async () => {
        // The scanner is shared across everyone asking the same question, so it holds older rows too.
        results = [observation('a', 'succeeded'), observation('someone-elses-session', 'succeeded')]
        logic = replayVisionScanWidgetLogic({ scanId: SCAN_ID, sessionIds: ['a'] })
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ observations: [expect.objectContaining({ session_id: 'a' })], pendingCount: 0 })
    })
})
