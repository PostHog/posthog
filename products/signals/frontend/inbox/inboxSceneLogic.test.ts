/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { OriginProduct, Task, TaskRun, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'
import { RuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { inboxSceneLogic, mergeSignalRuns } from './inboxSceneLogic'
import { SignalScoutRunSummary } from './types'

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
})
