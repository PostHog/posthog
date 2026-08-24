import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { observationsDockLogic } from './observationsDockLogic'
import { visionDockPreferenceLogic } from './visionDockPreferenceLogic'
import { visionScannersListLogic } from './visionScannersListLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { success: jest.fn(), info: jest.fn(), warning: jest.fn(), error: jest.fn() },
}))

function summaryObservation(): ReplayObservationApi {
    return {
        id: 'obs-summary',
        scanner_id: 'scanner-x',
        session_id: 'sess-1',
        status: 'succeeded',
        scanner_snapshot: { scanner_type: 'summarizer' },
    } as ReplayObservationApi
}

describe('observationsDockLogic', () => {
    let logic: ReturnType<typeof observationsDockLogic.build>
    let preferences: ReturnType<typeof visionDockPreferenceLogic.build>
    let observeCalls: number
    let inlineScanCalls: number
    let releaseObserve: () => void
    let releaseInlineScan: () => void
    let releaseScanners: () => void
    let inlineScanOutcome: string
    let observationResults: ReplayObservationApi[]

    beforeEach(() => {
        jest.clearAllMocks()
        observeCalls = 0
        inlineScanCalls = 0
        inlineScanOutcome = 'started'
        observationResults = []
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': async () => {
                    await new Promise<void>((resolve) => {
                        releaseScanners = resolve
                    })
                    return [200, { results: [] }]
                },
                '/api/projects/:team/vision/observations/': () => [200, { results: observationResults }],
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
        // Persisted, so a collapse in one test would otherwise decide the next test's starting state.
        preferences = visionDockPreferenceLogic()
        preferences.mount()
        preferences.actions.setSummaryDockAutoExpand(true)
        logic = observationsDockLogic({ sessionId: 'sess-1' })
        logic.mount()
    })

    afterEach(() => {
        releaseObserve?.()
        releaseInlineScan?.()
        releaseScanners?.()
        logic?.unmount()
        preferences?.unmount()
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

    it('warns rather than promising a result when an already-summarized row is unreadable', async () => {
        // The slot check runs unscoped, so `already_scanned` can come back for a row RBAC hides from the
        // dock, or the reload can fail. The old copy claimed a result over an empty dock; guard that the
        // reload happens first and the message admits nothing is shown.
        inlineScanOutcome = 'already_scanned'
        // Consume the mount-time load so its response can't overwrite the reload below.
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])

        logic.actions.summarize()
        // The mock holds the request open, and its release hook only exists once the handler runs.
        await new Promise((resolve) => setTimeout(resolve, 0))
        releaseInlineScan()

        await expectLogic(logic).toDispatchActions(['summarizeFailure', 'loadObservationsSuccess'])
        await expectLogic(logic).toMatchValues({ dockOpen: true, observations: [] })
        expect(lemonToast.warning).toHaveBeenCalled()
        expect(lemonToast.info).not.toHaveBeenCalled()
    })

    it('confirms the result when the already-summarized row is readable', async () => {
        // The reload surfaces the inline scanner's row (matched by scan_id), so the dock can point at it.
        inlineScanOutcome = 'already_scanned'
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])
        observationResults = [
            { id: 'obs-1', scanner_id: 'scanner-x', session_id: 'sess-1', status: 'succeeded' } as ReplayObservationApi,
        ]

        logic.actions.summarize()
        await new Promise((resolve) => setTimeout(resolve, 0))
        releaseInlineScan()

        await expectLogic(logic).toDispatchActions(['summarizeFailure', 'loadObservationsSuccess'])
        await expectLogic(logic).toMatchValues({ dockOpen: true, observations: observationResults })
        expect(lemonToast.info).toHaveBeenCalled()
        expect(lemonToast.warning).not.toHaveBeenCalled()
    })

    it('opens the dock for a recording that already has a summary', async () => {
        observationResults = [summaryObservation()]

        logic.actions.loadObservations()

        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])
        await expectLogic(logic).toMatchValues({ dockOpen: true })
    })

    it('leaves the dock closed on the next recording once the user collapses it', async () => {
        // The preference has to outlive the dock logic, which is keyed by session. Held per key, a
        // collapse would be forgotten the moment the user clicks the next recording in the playlist.
        observationResults = [summaryObservation()]
        logic.actions.loadObservations()
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])

        logic.actions.setDockOpen(false)

        const nextRecording = observationsDockLogic({ sessionId: 'sess-2' })
        nextRecording.mount()
        await expectLogic(nextRecording).toDispatchActions(['loadObservationsSuccess'])
        await expectLogic(nextRecording).toMatchValues({ dockOpen: false })
        nextRecording.unmount()
    })
})
