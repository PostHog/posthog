import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { observationsDockLogic } from './observationsDockLogic'
import { visionScannersListLogic } from './visionScannersListLogic'

describe('observationsDockLogic', () => {
    let logic: ReturnType<typeof observationsDockLogic.build>
    let observeCalls: number
    let inlineScanCalls: number
    let releaseObserve: () => void
    let releaseInlineScan: () => void
    let releaseScanners: () => void
    let inlineScanOutcome: string

    beforeEach(() => {
        observeCalls = 0
        inlineScanCalls = 0
        inlineScanOutcome = 'started'
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': async () => {
                    await new Promise<void>((resolve) => {
                        releaseScanners = resolve
                    })
                    return [200, { results: [] }]
                },
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
                '/api/projects/:team/vision/scanners/inline_scan/': async () => {
                    inlineScanCalls += 1
                    await new Promise<void>((resolve) => {
                        releaseInlineScan = resolve
                    })
                    return [
                        202,
                        {
                            scan_id: 'scanner-x',
                            started: inlineScanOutcome === 'started' ? 1 : 0,
                            results: [{ session_id: 'sess-1', scan_outcome: inlineScanOutcome }],
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = observationsDockLogic({ sessionId: 'sess-1' })
        logic.mount()
    })

    afterEach(() => {
        releaseObserve?.()
        releaseInlineScan?.()
        releaseScanners?.()
        logic?.unmount()
    })

    // Regression guard: the picker used `scanners.length === 0` alone to decide when to show the
    // "No scanners yet" dead-end link, so it rendered that link during the initial fetch too — the
    // exact window `scannersLoading` exists to distinguish from a team that truly has none.
    it('reports scanners as loading until the fetch resolves', async () => {
        await expectLogic(logic).toMatchValues({ scanners: [], scannersLoading: true })

        releaseScanners()
        await expectLogic(visionScannersListLogic).toDispatchActions(['loadScannersSuccess'])
        await expectLogic(logic).toMatchValues({ scannersLoading: false })
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

    it('starts one inline scan when summarize is clicked twice', async () => {
        // Same race as `observe`, but the summarize path guards itself with its own cache flag, so the
        // observe test can't cover it. A second POST spends nothing but contradicts the first toast.
        logic.actions.summarize()
        logic.actions.summarize()
        await expectLogic(logic).toMatchValues({ summarizing: true })
        await new Promise((resolve) => setTimeout(resolve, 0))
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(inlineScanCalls).toBe(1)
    })

    it('re-reads observations when the recording was already summarized', async () => {
        // The inline scanner is shared across the project, so the existing row can postdate this dock's
        // mount-time load. Without the refetch the user reads "already summarized" over an empty dock.
        inlineScanOutcome = 'already_scanned'
        logic.actions.summarize()
        // The mock holds the request open, and its release hook only exists once the handler runs.
        await new Promise((resolve) => setTimeout(resolve, 0))
        releaseInlineScan()

        await expectLogic(logic).toDispatchActions(['summarizeFailure', 'loadObservations'])
        await expectLogic(logic).toMatchValues({ dockOpen: true })
    })
})
