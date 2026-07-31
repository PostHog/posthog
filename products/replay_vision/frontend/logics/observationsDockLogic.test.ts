import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { observationsDockLogic } from './observationsDockLogic'

describe('observationsDockLogic', () => {
    let logic: ReturnType<typeof observationsDockLogic.build>
    let observeCalls: number
    let releaseObserve: () => void

    beforeEach(() => {
        observeCalls = 0
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': () => [200, { results: [] }],
                '/api/projects/:team/vision/observations/': () => [200, { results: [] }],
            },
            post: {
                '/api/projects/:team/vision/scanners/:id/observe/': async () => {
                    observeCalls += 1
                    // Hold the request open so a second click lands while the first is still in flight.
                    await new Promise<void>((resolve) => {
                        releaseObserve = resolve
                    })
                    return [202, { workflow_id: 'wf-1' }]
                },
            },
        })
        initKeaTests()
        logic = observationsDockLogic({ sessionId: 'sess-1' })
        logic.mount()
    })

    afterEach(() => {
        releaseObserve?.()
        logic?.unmount()
    })

    it('starts one observation when the same scanner row is clicked twice', async () => {
        // The picker rows disable while observing, but both click events can land before React re-renders,
        // and the duplicate-scanner guard can't see a run that has no observation row yet. Two POSTs mean a
        // second, contradictory toast on a request the backend refuses anyway.
        logic.actions.observe('scanner-1')
        logic.actions.observe('scanner-1')
        await expectLogic(logic).toMatchValues({ observing: true })
        // Let both listeners reach (or skip) their request before counting.
        await new Promise((resolve) => setTimeout(resolve, 0))
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(observeCalls).toBe(1)
    })
})
