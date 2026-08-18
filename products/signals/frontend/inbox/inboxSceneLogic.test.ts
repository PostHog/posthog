import { router } from 'kea-router'

import { OriginProduct, Task, TaskRun, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'
import { RuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { setInboxArrival } from './inboxAnalytics'
import { consumeArrivalParams, mergeSignalRuns } from './inboxSceneLogic'
import { SignalScoutRunSummary } from './types'

jest.mock('./inboxAnalytics', () => ({
    ...jest.requireActual('./inboxAnalytics'),
    setInboxArrival: jest.fn(),
}))

jest.mock('kea-router', () => ({
    ...jest.requireActual('kea-router'),
    router: {
        actions: { replace: jest.fn() },
        values: { location: { pathname: '/project/2/inbox/reports/r1' }, hashParams: {} },
    },
}))

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
        runtime: RuntimeEnumApi.Acp,
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

describe('consumeArrivalParams', () => {
    beforeEach(() => {
        ;(setInboxArrival as jest.Mock).mockClear()
        ;(router.actions.replace as jest.Mock).mockClear()
    })

    it('records the channel and send from a tagged notification link', () => {
        consumeArrivalParams({ nid: 'n-1', utm_source: 'slack', utm_content: 'inbox_card_team', tab: 'pulls' })

        expect(setInboxArrival).toHaveBeenCalledWith({
            notificationId: 'n-1',
            channel: 'slack',
            surface: 'inbox_card_team',
        })
    })

    it('strips the send id but keeps the campaign parameters', () => {
        // The send id has to go, or a refresh reads as a second click on the same notification.
        // The utm parameters have to stay: posthog-js reads them off the live URL.
        consumeArrivalParams({ nid: 'n-1', utm_source: 'slack', utm_medium: 'notification', tab: 'pulls' })

        const [, searchParams] = (router.actions.replace as jest.Mock).mock.calls[0]
        expect(searchParams).toEqual({ utm_source: 'slack', utm_medium: 'notification', tab: 'pulls' })
    })

    it('leaves an untagged visit alone', () => {
        consumeArrivalParams({ tab: 'pulls' })

        expect(setInboxArrival).not.toHaveBeenCalled()
        expect(router.actions.replace).not.toHaveBeenCalled()
    })
})
