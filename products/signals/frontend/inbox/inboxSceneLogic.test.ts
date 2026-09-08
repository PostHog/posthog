import { combineUrl, router } from 'kea-router'
/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { OriginProduct, Task, TaskRun, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'
import { TaskRuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { inboxSceneLogic, mergeSignalRuns } from './inboxSceneLogic'
import { reportListLogic, sectionListLogicProps } from './logics/reportListLogic'
import { SignalReport, SignalScoutRunSummary } from './types'

function openedEvents(spy: jest.SpyInstance): Record<string, any>[] {
    return spy.mock.calls
        .filter((call) => call[0] === 'Inbox report opened')
        .map((call) => call[1] as Record<string, any>)
}

function waitForOpenRankRetry(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 400))
}

function scoutRun(overrides: Partial<SignalScoutRunSummary> = {}): SignalScoutRunSummary {
    return {
        run_id: 'run-1',
        skill_name: 'signals-scout-error-tracking',
        skill_version: 1,
        status: 'completed',
        metadata: {},
        created_at: '2026-06-11T10:00:00Z',
        started_at: '2026-06-11T10:00:00Z',
        completed_at: null,
        task_id: 'task-scout',
        summary: '',
        emitted_count: 0,
        emitted_finding_ids: [],
        emitted_report_ids: [],
        edited_report_ids: [],
        ...overrides,
    }
}

function signalTask(overrides: Partial<Task> = {}): Task {
    return {
        id: 'task-signal',
        task_number: null,
        slug: '',
        title: 'Crash on login',
        description: '',
        origin_product: OriginProduct.SIGNAL_REPORT,
        runtime: TaskRuntimeEnumApi.Acp,
        repository: null,
        github_integration: null,
        signal_report: 'report-1',
        json_schema: null,
        internal: false,
        latest_run: null,
        created_at: '2026-06-11T09:00:00Z',
        updated_at: '2026-06-11T09:00:00Z',
        created_by: null,
        ...overrides,
    }
}

describe('mergeSignalRuns', () => {
    it('drops scout runs without a backing task_id (they cannot deep-link to a task)', () => {
        const merged = mergeSignalRuns([scoutRun({ task_id: null }), scoutRun({ task_id: 'task-ok' })], [])
        expect(merged.map((r) => r.task_id)).toEqual(['task-ok'])
    })

    it('drops signal tasks with no report link (the scout-authoring CTA threads share the origin)', () => {
        const merged = mergeSignalRuns(
            [],
            [signalTask({ id: 'scout-authoring-chat', title: 'Suggest a scout', signal_report: null })]
        )
        expect(merged).toEqual([])
    })

    it('interleaves scout and signal rows newest-first by created_at', () => {
        const merged = mergeSignalRuns(
            [scoutRun({ task_id: 'scout-old', created_at: '2026-06-10T00:00:00Z' })],
            [signalTask({ id: 'signal-new', created_at: '2026-06-12T00:00:00Z' })]
        )
        expect(merged.map((r) => r.task_id)).toEqual(['signal-new', 'scout-old'])
    })

    it('tags kind and title per source (scout → skill_name, signal → report title)', () => {
        const [scoutRow, signalRow] = mergeSignalRuns(
            [scoutRun({ task_id: 'scout', skill_name: 'signals-scout-surveys', created_at: '2026-06-11T11:00:00Z' })],
            [signalTask({ id: 'signal', title: 'Slow query', created_at: '2026-06-11T08:00:00Z' })]
        )
        expect(scoutRow).toMatchObject({ kind: 'scout', title: 'signals-scout-surveys', report_id: null })
        expect(signalRow).toMatchObject({ kind: 'signal', title: 'Slow query', report_id: 'report-1' })
    })

    it('falls back to the task timestamp and a null status when a signal task has no run', () => {
        const [row] = mergeSignalRuns([], [signalTask({ latest_run: null, created_at: '2026-06-11T07:00:00Z' })])
        expect(row).toMatchObject({ status: null, created_at: '2026-06-11T07:00:00Z' })
    })

    it("maps the latest run's task status to the scout status string, and uses the run's timestamp", () => {
        const latest_run = {
            status: TaskRunStatus.IN_PROGRESS,
            created_at: '2026-06-11T12:00:00Z',
        } as TaskRun
        const [row] = mergeSignalRuns([], [signalTask({ latest_run, created_at: '2026-06-11T07:00:00Z' })])
        // The `TaskRunStatus` enum is bridged to the equivalent `SignalScoutRunStatus` string the row
        // field holds (here 'in_progress'), and the run's own timestamp wins over the task's.
        expect(row).toMatchObject({ status: 'in_progress', created_at: '2026-06-11T12:00:00Z' })
    })
})

// Slack links, bookmarks, and other products carry `/inbox/<tab>` segments from either layout, so
// each layout has to land the other's segments on its own surface instead of dropping them.
describe('inboxSceneLogic routing', () => {
    let logic: ReturnType<typeof inboxSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                '/api/projects/:team_id/signals/reports/': { results: [], count: 0, next: null, previous: null },
                '/api/projects/:team_id/signals/source_configs/': { results: [] },
                '/api/projects/:team_id/signals/scout/configs/': [],
            },
        })
        // The list-visited flag lives in session storage, so it outlives a test.
        window.sessionStorage.clear()
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => logic?.unmount())

    function mountWithRedesign(enabled: boolean): void {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
            [FEATURE_FLAGS.INBOX_REDESIGN]: enabled,
        })
        logic = inboxSceneLogic()
        logic.mount()
    }

    it.each<[string, string, string]>([
        ['/inbox/pulls', urls.inbox('reports'), 'reports'],
        ['/inbox/archived', urls.inbox('reports'), 'reports'],
        ['/inbox/config', urls.inbox('settings'), 'settings'],
        ['/inbox/runs', urls.inboxRuns(), 'scouts'],
        ['/inbox/pulls/report-1', urls.inboxReport('reports', 'report-1'), 'reports'],
    ])('under the redesign %s lands on %s', (path, expectedPath, expectedTab) => {
        mountWithRedesign(true)
        router.actions.push(path)
        expect(router.values.location.pathname.endsWith(expectedPath)).toBe(true)
        expect(logic.values.activeTab).toBe(expectedTab)
    })

    it.each<[string, string, string]>([
        ['/inbox/settings', urls.inbox('config'), 'config'],
        ['/inbox/scouts/runs', urls.inbox('runs'), 'runs'],
        ['/inbox/reports/triage', urls.inbox('reports'), 'reports'],
        ['/inbox/pulls', urls.inbox('pulls'), 'pulls'],
        ['/inbox/pulls/report-1', urls.inboxReport('pulls', 'report-1'), 'pulls'],
    ])('with the flag off %s lands on %s', (path, expectedPath, expectedTab) => {
        mountWithRedesign(false)
        router.actions.push(path)
        expect(router.values.location.pathname.endsWith(expectedPath)).toBe(true)
        expect(logic.values.activeTab).toBe(expectedTab)
    })

    it.each([
        [true, 'reports'],
        [false, 'pulls'],
    ])('with the redesign flag %p a bare /inbox lands on the %s tab', (enabled, expectedTab) => {
        mountWithRedesign(enabled)
        router.actions.push(urls.inbox())
        expect(logic.values.activeTab).toBe(expectedTab)
    })

    // A flag that flips mid-session leaves the URL addressed to the other layout. The current URL is
    // routed again for the new layout, so its surface opens rather than a tab body that renders nothing.
    it.each<[boolean, string, string, string]>([
        [false, '/inbox/runs', urls.inboxRuns(), 'scouts'],
        [true, '/inbox/settings', urls.inbox('config'), 'config'],
    ])('a mid-session flag flip (from redesign=%p) re-routes %s to %s', (initial, path, expectedPath, expectedTab) => {
        mountWithRedesign(initial)
        router.actions.push(path)
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
            [FEATURE_FLAGS.INBOX_REDESIGN]: !initial,
        })
        expect(router.values.location.pathname.endsWith(expectedPath)).toBe(true)
        expect(logic.values.activeTab).toBe(expectedTab)
    })

    function mountBeforeFlagsResolve(persistedRedesign: boolean): void {
        // `featureFlags` persists through kea-localstorage, so a cold load routes against the value the
        // last visit stored until PostHog answers. Seed that value and leave `receivedFeatureFlags` false.
        window.localStorage.setItem(
            'lib.logic.featureFlagLogic.featureFlags',
            JSON.stringify({ [FEATURE_FLAGS.INBOX_REDESIGN]: persistedRedesign })
        )
        initKeaTests()
        featureFlagLogic.mount()
        logic = inboxSceneLogic()
        logic.mount()
    }

    // On a cold load the route handlers run before PostHog returns flags. A layout redirect issued then
    // would erase the surface the URL names, so the URL is held and routed again once flags land.
    it.each<[string, boolean, string, (values: typeof logic.values) => boolean]>([
        ['/inbox/reports/triage', true, urls.inboxTriage(), (values) => values.isTriageOpen],
        ['/inbox/scouts/runs', true, urls.inboxRuns(), (values) => values.isRunsOpen],
        ['/inbox/pulls', true, urls.inbox('reports'), (values) => values.activeTab === 'reports'],
        ['/inbox/settings', false, urls.inbox('config'), (values) => values.activeTab === 'config'],
    ])('before flags resolve %s is held, then routed for redesign=%p to %s', (path, redesign, expectedPath, opened) => {
        mountBeforeFlagsResolve(!redesign)
        router.actions.push(path)
        expect(router.values.location.pathname.endsWith(path)).toBe(true)
        expect(opened(logic.values)).toBe(false)
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
            [FEATURE_FLAGS.INBOX_REDESIGN]: redesign,
        })
        expect(router.values.location.pathname.endsWith(expectedPath)).toBe(true)
        expect(opened(logic.values)).toBe(true)
    })

    // A held report deep-link still opens the report under the persisted layout, so the page is not
    // empty while flags load; the replay only settles the tab once the layout is known.
    it('before flags resolve /inbox/pulls/<id> opens the report and lands on Reports once the redesign resolves', () => {
        mountBeforeFlagsResolve(true)
        router.actions.push('/inbox/pulls/report-1')
        expect(logic.values.selectedReportId).toBe('report-1')
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
            [FEATURE_FLAGS.INBOX_REDESIGN]: true,
        })
        expect(router.values.location.pathname.endsWith(urls.inboxReport('reports', 'report-1'))).toBe(true)
        expect(logic.values.selectedReportId).toBe('report-1')
        expect(logic.values.activeTab).toBe('reports')
    })

    // The triage card's "Full report" link opens the report by URL (with a triage `back`), not through
    // `openCurrent`, so the open-method must be recovered from that `back` or triage opens split between
    // the `triage` and `click` analytics values.
    it.each<[string, boolean, string]>([
        ['a triage back link records the triage open method', true, 'triage'],
        ['a plain report deep-link is not attributed to triage', false, 'deeplink'],
    ])('%s', async (_name, withTriageBack, expectedMethod) => {
        mountWithRedesign(true)
        const url = withTriageBack
            ? combineUrl(urls.inboxReport('reports', 'r1'), {
                  back: combineUrl(urls.inboxTriage(), { report: 'r1', at: 0 }).url,
              }).url
            : urls.inboxReport('reports', 'r1')

        let openMethod: string | undefined
        await expectLogic(logic, () => router.actions.push(url)).toDispatchActions([
            (action: any) => {
                if (action.type !== logic.actionTypes.setSelectedReportId) {
                    return false
                }
                openMethod = action.payload.openMethod
                return true
            },
        ])
        expect(openMethod).toBe(expectedMethod)
    })

    // A reload, a new tab, and a bundle update each start a fresh logic.
    it('a report URL loaded fresh after the list was visited this session is a click, not a deep-link', async () => {
        mountWithRedesign(true)
        router.actions.push(urls.inbox('reports'))
        logic.unmount()

        initKeaTests()
        featureFlagLogic.mount()
        mountWithRedesign(true)

        let openMethod: string | undefined
        await expectLogic(logic, () => router.actions.push(urls.inboxReport('reports', 'r1'))).toDispatchActions([
            (action: any) => {
                if (action.type !== logic.actionTypes.setSelectedReportId) {
                    return false
                }
                openMethod = action.payload.openMethod
                return true
            },
        ])
        expect(openMethod).toBe('click')
    })

    // A rank read at open time is null on a cold load, and joins to no impression row.
    it('holds `Inbox report opened` until the list answers, then reports the rank', async () => {
        const report = { id: 'r1', title: 'Crash on login' } as SignalReport
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': {
                    results: [report],
                    count: 1,
                    next: null,
                    previous: null,
                },
            },
        })
        const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        mountWithRedesign(false)
        const listLogic = reportListLogic(sectionListLogicProps('needs-decision'))
        listLogic.mount()
        listLogic.actions.loadReports()

        logic.actions.setSelectedReportId('r1')
        logic.actions.loadSelectedReportSuccess(report)
        expect(openedEvents(captureSpy)).toHaveLength(0)

        await waitForOpenRankRetry()

        expect(openedEvents(captureSpy)[0]).toMatchObject({ rank: 1, list_size: 1 })
        captureSpy.mockRestore()
        listLogic.unmount()
    })

    // The flat list merges every selected state, so a state that answers late can add rows that sort
    // above the report. Ranking on the first state to answer records a rank that is too small, and
    // the impression side (which waits for all of them) then records a different one.
    it('under the flat list the rank waits for the slower state, not the first one to answer', async () => {
        const opened = { id: 'r1', title: 'Crash on login', priority: 'P2' } as SignalReport
        const higher = { id: 'r2', title: 'Checkout times out', priority: 'P0' } as SignalReport
        let releaseMonitoring = (): void => {}
        const monitoringAnswered = new Promise<void>((resolve) => {
            releaseMonitoring = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': async ({ request }) => {
                    // Only the monitoring state filters on an open implementation PR.
                    if (new URL(request.url).searchParams.get('has_implementation_pr') === 'true') {
                        await monitoringAnswered
                        return [200, { results: [higher], count: 1, next: null, previous: null }]
                    }
                    return [200, { results: [opened], count: 1, next: null, previous: null }]
                },
            },
        })
        const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        mountWithRedesign(true)
        const needsDecision = reportListLogic(sectionListLogicProps('needs-decision'))
        const monitoring = reportListLogic(sectionListLogicProps('monitoring'))
        needsDecision.mount()
        monitoring.mount()
        needsDecision.actions.loadReports()
        monitoring.actions.loadReports()

        logic.actions.setSelectedReportId('r1')
        logic.actions.loadSelectedReportSuccess(opened)

        await waitForOpenRankRetry()
        expect(needsDecision.values.reports).toHaveLength(1)
        expect(openedEvents(captureSpy)).toHaveLength(0)

        releaseMonitoring()
        await waitForOpenRankRetry()

        expect(openedEvents(captureSpy)[0]).toMatchObject({ rank: 2, list_size: 2 })
        captureSpy.mockRestore()
        needsDecision.unmount()
        monitoring.unmount()
    })

    // posthog-js drains its batch queue from its own `pagehide` handler, which is registered before
    // this scene's. An open left to normal batching is enqueued after that drain and never leaves.
    it('a page unload while an open is still waiting sends the open instantly, ahead of the close', () => {
        const report = { id: 'r1', title: 'Crash on login' } as SignalReport
        const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        mountWithRedesign(true)

        // No list is mounted, so the rank never resolves and the open stays pending.
        logic.actions.setSelectedReportId('r1')
        logic.actions.loadSelectedReportSuccess(report)
        expect(openedEvents(captureSpy)).toHaveLength(0)

        window.dispatchEvent(new Event('pagehide'))

        const inboxCalls = captureSpy.mock.calls.filter(([name]) =>
            ['Inbox report opened', 'Inbox report closed'].includes(name as string)
        )
        expect(inboxCalls.map(([name]) => name)).toEqual(['Inbox report opened', 'Inbox report closed'])
        expect(inboxCalls[0][2]).toEqual({ send_instantly: true })
        expect(inboxCalls[1][2]).toEqual({ send_instantly: true })
        captureSpy.mockRestore()
    })

    it('stops the runs poll when opening another surface closes the panel', () => {
        // Opening a report flips `isRunsOpen` false through a mutual-exclusion reducer, not
        // `setRunsOpen(false)`, so the poll teardown cannot hang off the `setRunsOpen` listener alone
        // or it leaks two requests every few seconds for the rest of the visit.
        mountWithRedesign(true)
        const clearSpy = jest.spyOn(global, 'clearInterval')

        logic.actions.setRunsOpen(true)
        const clearedBeforeReport = clearSpy.mock.calls.length

        logic.actions.setSelectedReportId('report-1')

        expect(logic.values.isRunsOpen).toBe(false)
        expect(clearSpy.mock.calls.length).toBeGreaterThan(clearedBeforeReport)

        clearSpy.mockRestore()
    })
})
