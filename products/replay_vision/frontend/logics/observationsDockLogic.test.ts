import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ReplayObservationApi, ReplayScannerApi } from '../generated/api.schemas'
import { OBSERVE_POLL_GRACE_MS } from './observationPolling'
import { observationsDockLogic } from './observationsDockLogic'
import { visionDockPreferenceLogic } from './visionDockPreferenceLogic'
import { visionScannersListLogic } from './visionScannersListLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { success: jest.fn(), info: jest.fn(), warning: jest.fn(), error: jest.fn() },
}))

function scanner(id: string, scannerType: string): ReplayScannerApi {
    return { id, name: `Scanner ${id}`, scanner_type: scannerType } as ReplayScannerApi
}

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
    let observationsFail: boolean
    let scannerResults: ReplayScannerApi[]

    beforeEach(() => {
        jest.clearAllMocks()
        observeCalls = 0
        inlineScanCalls = 0
        inlineScanOutcome = 'started'
        observationResults = []
        observationsFail = false
        scannerResults = []
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': async () => {
                    await new Promise<void>((resolve) => {
                        releaseScanners = resolve
                    })
                    return [200, { results: scannerResults }]
                },
                '/api/projects/:team/vision/observations/': () =>
                    observationsFail ? [500, {}] : [200, { results: observationResults }],
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
        preferences.actions.setPreferredSummarizerId(null)
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
        // The second click is dropped, but it now says so rather than leaving the user in front of a
        // button that looked live and did nothing.
        expect(lemonToast.info).toHaveBeenCalled()
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

    const loadScanners = async (scanners: ReplayScannerApi[]): Promise<void> => {
        scannerResults = scanners
        // The mock holds the scanner fetch open, and its release hook only exists once the handler runs.
        await new Promise((resolve) => setTimeout(resolve, 0))
        releaseScanners()
        await expectLogic(visionScannersListLogic).toDispatchActions(['loadScannersSuccess'])
    }

    // Which scanner it resolves to is settled by `resolveSummarizer` and tested there. What only this
    // level shows is that the two answers reach two different endpoints: a scanner runs through
    // `observe`, and the built-in prompt through `inline_scan`.
    test.each([
        { shape: 'a summarizer of their own', scanners: [scanner('s1', 'summarizer')], runsOwnScanner: true },
        { shape: 'no summarizer', scanners: [scanner('m1', 'monitor')], runsOwnScanner: false },
    ])('summarize with $shape runs own scanner: $runsOwnScanner', async (routingCase) => {
        await loadScanners(routingCase.scanners)

        logic.actions.summarize()
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(observeCalls).toBe(routingCase.runsOwnScanner ? 1 : 0)
        expect(inlineScanCalls).toBe(routingCase.runsOwnScanner ? 0 : 1)
    })

    it('stays pending while a summary row is still running, and settles once it is not', async () => {
        // The reason the button kept reverting mid-scan: the old spinner cleared on the trigger
        // response, not on the summary itself. `summarizePending` reads the row's own status, so it
        // holds a recording that was opened with a summary already in flight, then clears when the
        // scan lands — no click needed to reproduce either state.
        const runningRow = {
            id: 'obs-run',
            scanner_id: 'scanner-x',
            session_id: 'sess-1',
            status: 'running',
            scanner_snapshot: { scanner_type: 'summarizer' },
        } as ReplayObservationApi

        observationResults = [runningRow]
        logic.actions.loadObservations()
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])
        await expectLogic(logic).toMatchValues({ summaryInFlight: true, summarizePending: true })

        observationResults = [{ ...runningRow, status: 'succeeded' } as ReplayObservationApi]
        logic.actions.loadObservations()
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])
        await expectLogic(logic).toMatchValues({ summaryInFlight: false, summarizePending: false })
    })

    it('does not treat a running monitor scan as a summary in flight', async () => {
        // The summarize button only owns summaries. A monitor scan the sidebar started is in flight
        // too, but claiming it here would leave the button pending over a run it never triggered.
        observationResults = [
            {
                id: 'obs-mon',
                scanner_id: 'scanner-m',
                session_id: 'sess-1',
                status: 'running',
                scanner_snapshot: { scanner_type: 'monitor' },
            } as ReplayObservationApi,
        ]
        logic.actions.loadObservations()
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])
        await expectLogic(logic).toMatchValues({ summaryInFlight: false, summarizePending: false })
    })

    it('keeps the summary pending when a scan the sidebar started fails', async () => {
        // The sidebar picker runs on this same keyed logic, so its `observeFailure` arrives on the
        // summary's reducer. It used to clear the button, putting the idle label back under a user
        // whose summary was still running — the exact symptom this PR removes.
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])
        observationResults = [
            { id: 'obs-mon', scanner_id: 'm1', session_id: 'sess-1', status: 'succeeded' } as ReplayObservationApi,
        ]
        logic.actions.loadObservations()
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])

        logic.actions.summarize()
        await expectLogic(logic).toMatchValues({ summarizePending: true })

        // A sidebar pick of a scanner that already ran here, which is one of the failure paths.
        logic.actions.observe('m1')

        await expectLogic(logic).toDispatchActions(['observeFailure'])
        await expectLogic(logic).toMatchValues({ summarizePending: true })
    })

    // Both triggers share one in-flight guard, so which run the guard rejected decides whether the
    // button still has a summary to wait for. Rejecting the click either way is what the guard is
    // for; leaving it pending over a scan it never started is not.
    test.each([
        { blocker: 'a sidebar scan', firstClick: (): void => logic.actions.observe('m1'), stillPending: false },
        { blocker: 'its own first click', firstClick: (): void => logic.actions.summarize(), stillPending: true },
    ])('summarize blocked by $blocker stays pending: $stillPending', async (guardCase) => {
        await loadScanners([scanner('s1', 'summarizer'), scanner('m1', 'monitor')])

        guardCase.firstClick()
        // Let the first request reach the mock, so its in-flight flag is set before the next click.
        await new Promise((resolve) => setTimeout(resolve, 0))
        logic.actions.summarize()
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(observeCalls).toBe(1)
        expect(lemonToast.info).toHaveBeenCalled()
        await expectLogic(logic).toMatchValues({ summarizePending: guardCase.stillPending })
    })

    it('settles the button when a fast summary lands inside the grace window', async () => {
        // The grace window covers the wait for a row that does not exist yet. A summary that finished
        // inside it used to hold the button on "Summarizing…" for the rest of the window, right next
        // to the finished summary the dock had already rendered.
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])
        logic.actions.summarize()
        await new Promise((resolve) => setTimeout(resolve, 0))
        releaseInlineScan()
        await expectLogic(logic).toDispatchActions(['summarizeSuccess'])
        await expectLogic(logic).toMatchValues({ summarizePending: true })

        // The row this scan created, terminal while the grace window is still open.
        observationResults = [summaryObservation()]
        logic.actions.loadObservations()

        await expectLogic(logic).toDispatchActions(['summarizeSettled'])
        await expectLogic(logic).toMatchValues({ summarizePending: false })
    })

    it('settles the button while an unrelated sidebar scan is still being started', async () => {
        // `observeInFlight` names which run is open. Gating on it being set at all let a sidebar scan's
        // open request hold "Summarizing…" after the summary itself had already settled.
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])
        logic.actions.summarize()
        await new Promise((resolve) => setTimeout(resolve, 0))
        releaseInlineScan()
        await expectLogic(logic).toDispatchActions(['summarizeSuccess'])

        // A monitor scan started from the sidebar, its request still open.
        logic.actions.observe('m1')
        await new Promise((resolve) => setTimeout(resolve, 0))

        observationResults = [summaryObservation()]
        logic.actions.loadObservations()

        await expectLogic(logic).toDispatchActions(['summarizeSettled'])
        await expectLogic(logic).toMatchValues({ summarizePending: false })
    })

    it('keeps the button pending while the scanner it started has no row yet', async () => {
        // The grace window ends on the row this run created, not on any summary row. A recording that
        // already carries an older summary must not settle the button for a second summarizer whose
        // own row is still on its way.
        await loadScanners([scanner('s1', 'summarizer')])
        observationResults = [summaryObservation()]
        logic.actions.loadObservations()
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])

        logic.actions.summarize()
        await new Promise((resolve) => setTimeout(resolve, 0))
        releaseObserve()
        await expectLogic(logic).toDispatchActions(['observeSuccess'])

        logic.actions.loadObservations()
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])
        await expectLogic(logic).toMatchValues({ summarizePending: true })
    })

    it('stops showing the summary as pending once the reload keeps failing', async () => {
        // With no summary row ever loaded, the grace window is the only thing keeping the poll alive.
        // A run of failed reloads used to stop polling with nothing left to clear the pending state,
        // so the button read "Summarizing…" until the dock remounted.
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])
        logic.actions.summarize()
        await new Promise((resolve) => setTimeout(resolve, 0))
        releaseInlineScan()
        await expectLogic(logic).toDispatchActions(['summarizeSuccess'])
        await expectLogic(logic).toMatchValues({ summarizePending: true })

        // Past the grace window with the row still absent, so the next failure is the last poll.
        const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(Date.now() + OBSERVE_POLL_GRACE_MS + 1)
        observationsFail = true
        logic.actions.loadObservations()

        await expectLogic(logic).toDispatchActions(['loadObservationsFailure', 'summarizeSettled'])
        await expectLogic(logic).toMatchValues({ summarizePending: false })
        nowSpy.mockRestore()
    })

    it('keeps the summarizer picked from the dropdown on the next recording', async () => {
        // Picking from the dropdown has to outlive the recording it was picked on, or a team with
        // several summarizers re-picks on every recording and the button never settles on their choice.
        await loadScanners([scanner('s1', 'summarizer'), scanner('s2', 'summarizer')])
        await expectLogic(logic).toMatchValues({ defaultSummarizer: null })

        logic.actions.summarizeWith('s2')

        const nextRecording = observationsDockLogic({ sessionId: 'sess-2' })
        nextRecording.mount()
        await expectLogic(nextRecording).toMatchValues({ defaultSummarizer: expect.objectContaining({ id: 's2' }) })
        nextRecording.unmount()
    })
})
