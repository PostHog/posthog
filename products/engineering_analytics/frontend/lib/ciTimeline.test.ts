import type { WorkflowJobApi } from '../generated/api.schemas'
import { buildPushTimeline, buildRunTimeline } from './ciTimeline'
import { WorkflowRun } from './lifecycle'

const NOW_MS = Date.parse('2026-06-10T00:00:00Z')
const REPO = { owner: 'PostHog', name: 'posthog' }

function job(id: number, name: string, startedAt: string, completedAt: string, conclusion = 'success'): WorkflowJobApi {
    return {
        id,
        run_id: 42,
        name,
        status: 'completed',
        conclusion,
        started_at: startedAt,
        completed_at: completedAt,
        duration_seconds: null,
        runner_provider: 'self_hosted',
        runner_label: 'depot-ubuntu-latest',
        estimated_cost_usd: null,
        ci_engine: 'github_actions',
        steps: [],
    }
}

function run(workflow: string, startedAt: string, finishedAt: string | null): WorkflowRun {
    return {
        workflow,
        conclusion: finishedAt ? 'success' : null,
        startedAt,
        finishedAt,
        durationSeconds: null,
        runId: workflow.length,
        runAttempt: 1,
    }
}

describe('ciTimeline', () => {
    test.each(['failure', 'startup_failure'])(
        'nests matrix shards under a group that fails on a %s shard',
        (conclusion) => {
            const timeline = buildRunTimeline(
                REPO,
                '2026-06-09T00:00:00Z',
                [
                    job(1, 'Jest (1/2)', '2026-06-09T00:01:00Z', '2026-06-09T00:03:00Z'),
                    job(2, 'Jest (2/2)', '2026-06-09T00:02:00Z', '2026-06-09T00:05:00Z', conclusion),
                ],
                NOW_MS
            )

            expect(timeline.nodes).toHaveLength(1)
            expect(timeline.nodes[0]).toMatchObject({
                kind: 'group',
                name: 'Jest',
                status: 'failure',
                startMs: Date.parse('2026-06-09T00:01:00Z'),
                endMs: Date.parse('2026-06-09T00:05:00Z'),
            })
            expect(timeline.nodes[0].children.map((child) => [child.name, child.url])).toEqual([
                ['Jest (1/2)', 'https://github.com/PostHog/posthog/actions/runs/42/job/1'],
                ['Jest (2/2)', 'https://github.com/PostHog/posthog/actions/runs/42/job/2'],
            ])
        }
    )

    test.each([
        ['still running', '2026-06-09T23:50:00Z', null, [], NOW_MS, 'running'],
        ['silent for over a day', '2026-06-01T00:00:00Z', null, [], null, 'neutral'],
        ['days long but updated recently', '2026-06-01T00:00:00Z', '2026-06-09T23:00:00Z', [], NOW_MS, 'running'],
        [
            'silent for over a day after a job finished',
            '2026-06-01T00:00:00Z',
            '2026-06-01T00:10:00Z',
            [job(1, 'Build', '2026-06-01T00:01:00Z', '2026-06-01T00:10:00Z')],
            null,
            'neutral',
        ],
    ])(
        'ends an unfinished run that is %s at the right time',
        (_, startedAt, updatedAt, jobs, expectedEndMs, expectedStatus) => {
            const timeline = buildPushTimeline(
                REPO,
                [
                    { id: 'lint', run: run('Lint', '2026-06-09T23:50:00Z', '2026-06-09T23:55:00Z'), jobs: [] },
                    { id: 'stuck', run: { ...run('Stuck', startedAt, null), updatedAt }, jobs },
                ],
                NOW_MS
            )

            expect(timeline.nodes.find((node) => node.name === 'Stuck')).toMatchObject({
                endMs: expectedEndMs,
                status: expectedStatus,
            })
            expect(timeline.endMs).toEqual(expectedEndMs ?? Date.parse('2026-06-09T23:55:00Z'))
        }
    )
})
