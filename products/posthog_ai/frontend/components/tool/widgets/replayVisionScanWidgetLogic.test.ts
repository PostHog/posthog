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

    it('keeps polling after a failed read', async () => {
        // The scanner is shared and the read can blip. Dropping the poll on the first failure leaves a
        // spinner on screen forever even though the results landed.
        let calls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/vision/scanners/:scanner_id/observations/': () => {
                    calls += 1
                    return calls === 1 ? [500, {}] : [200, { results: [observation('a', 'succeeded')] }]
                },
            },
        })
        logic = replayVisionScanWidgetLogic({ scanId: SCAN_ID, sessionIds: ['a'] })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.loadObservations()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ pendingCount: 0 })
    })

    it('counts two rows for one session once', async () => {
        // A retry adds a second row for the same session. Counting rows would call the scan complete
        // while another session is still running.
        results = [observation('a', 'succeeded'), observation('a', 'succeeded')]
        logic = replayVisionScanWidgetLogic({ scanId: SCAN_ID, sessionIds: ['a', 'b'] })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ pendingCount: 1 })
    })

    it('reads nothing back when the scan started nothing', async () => {
        // Every session skipped means no session filter, which the API reads as "no filter" and would
        // answer with the shared scanner's whole history under a "Scan complete" header.
        let requested = false
        useMocks({
            get: {
                '/api/projects/:team_id/vision/scanners/:scanner_id/observations/': () => {
                    requested = true
                    return [200, { results: [observation('someone-elses-session', 'succeeded')] }]
                },
            },
        })
        logic = replayVisionScanWidgetLogic({ scanId: SCAN_ID, sessionIds: [] })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ observations: [], pendingCount: 0 })

        expect(requested).toBe(false)
    })

    it('says so when it stops before every recording settled', async () => {
        // Polling stops after repeated failures. Without a visible give-up the widget keeps a spinner
        // on a recording it is no longer waiting for.
        useMocks({
            get: {
                '/api/projects/:team_id/vision/scanners/:scanner_id/observations/': () => [500, {}],
            },
        })
        logic = replayVisionScanWidgetLogic({ scanId: SCAN_ID, sessionIds: ['a'] })
        logic.mount()

        for (let attempt = 0; attempt < 5; attempt++) {
            logic.actions.loadObservations()
            await expectLogic(logic).toFinishAllListeners()
        }

        await expectLogic(logic).toMatchValues({ gaveUp: true, pendingCount: 1 })
    })

    it("asks the server for only this scan's sessions", async () => {
        // The scanner is shared across everyone asking the same question. Filtering client-side after a
        // page limit can return a page holding none of these sessions, so the filter has to be server-side.
        let requestedSessionIds: string | null = null
        useMocks({
            get: {
                '/api/projects/:team_id/vision/scanners/:scanner_id/observations/': ({ request }) => {
                    requestedSessionIds = new URL(request.url).searchParams.get('session_id')
                    return [200, { results: [observation('a', 'succeeded')] }]
                },
            },
        })
        logic = replayVisionScanWidgetLogic({ scanId: SCAN_ID, sessionIds: ['a', 'b'] })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedSessionIds).toBe('a,b')
    })
})
