import type { PRLifecycleApi, WorkflowRunDetailApi } from '../generated/api.schemas'
import { activityDays, commitRows } from './ciExplorerActivity'

function run(overrides: Partial<WorkflowRunDetailApi>): WorkflowRunDetailApi {
    return {
        repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
        id: 1,
        workflow_name: 'CI',
        head_sha: 'aaaaaaa1',
        head_branch: 'feature',
        status: 'completed',
        conclusion: 'success',
        run_started_at: '2026-06-01T10:00:00Z',
        updated_at: '2026-06-01T10:05:00Z',
        duration_seconds: 300,
        run_attempt: 1,
        pr_number: 10,
        commit_pr_number: null,
        is_merge_queue: false,
        ...overrides,
    }
}

const LIFECYCLE = {
    pull_request: { author: { handle: 'octocat' } },
    events: [
        { kind: 'opened', at: '2026-06-01T10:00:00Z' },
        { kind: 'ci_started', at: '2026-06-01T10:00:00Z', detail: 'CI' },
        { kind: 'ready_for_review', at: '2026-06-02T09:00:00Z', detail: 'hubot' },
    ],
} as unknown as PRLifecycleApi

describe('ciExplorerActivity', () => {
    it('orders people before the CI they started and leaves per-workflow CI events to the commit rows', () => {
        const days = activityDays(LIFECYCLE, commitRows([run({})]))

        expect(days.map((day) => day.rows.map((row) => (row.type === 'commit' ? 'commit' : row.kind)))).toEqual([
            ['opened', 'commit'],
            ['ready_for_review'],
        ])
        expect(days[0].rows[0]).toMatchObject({ actor: 'octocat' })
        expect(days[1].rows[0]).toMatchObject({ actor: 'hubot' })
    })

    it('counts failures as history and never marks a merge queue attempt as the current commit', () => {
        const runs = [
            run({ id: 1, conclusion: 'failure' }),
            run({ id: 2, run_started_at: '2026-06-01T10:20:00Z', updated_at: '2026-06-01T10:30:00Z' }),
            run({
                id: 3,
                head_sha: 'bbbbbbb2',
                is_merge_queue: true,
                run_started_at: '2026-06-01T12:00:00Z',
                updated_at: '2026-06-01T12:05:00Z',
            }),
        ]

        expect(commitRows(runs)).toMatchObject([
            { headSha: 'aaaaaaa1', runs: 2, failed: 1, elapsedSeconds: 1800, latest: true, mergeQueue: false },
            { headSha: 'bbbbbbb2', runs: 1, failed: 0, latest: false, mergeQueue: true },
        ])
    })
})
