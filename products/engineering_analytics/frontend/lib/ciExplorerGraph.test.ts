import type { WorkflowJobApi } from '../generated/api.schemas'
import { buildWorkflows, latestRunPerWorkflow } from './ciExplorerGraph'
import type { WorkflowRun } from './lifecycle'

function run(overrides: Partial<WorkflowRun>): WorkflowRun {
    return {
        workflow: 'Backend CI',
        workflowId: 100,
        ciEngine: 'github_actions',
        conclusion: 'success',
        startedAt: '2026-06-01T00:00:00Z',
        finishedAt: '2026-06-01T00:10:00Z',
        durationSeconds: 600,
        runId: 1,
        runAttempt: 1,
        ...overrides,
    }
}

describe('ciExplorerGraph', () => {
    test.each<[string, WorkflowRun[], [number, number][]]>([
        [
            'two providers that share a display name both stay',
            [run({ runId: 1 }), run({ runId: 2, ciEngine: 'depot_ci', workflowId: null })],
            [
                [1, 1],
                [2, 1],
            ],
        ],
        [
            'a renamed workflow is still one workflow, and its newest run stands for it',
            [
                run({ runId: 1, workflow: 'Backend CI' }),
                run({ runId: 2, workflow: 'Backend', startedAt: '2026-06-01T01:00:00Z' }),
            ],
            [[2, 1]],
        ],
        [
            'two workflows that share a display name both stay',
            [run({ runId: 1, workflowId: 100 }), run({ runId: 2, workflowId: 200 })],
            [
                [1, 1],
                [2, 1],
            ],
        ],
        [
            'a re-run that reports the same start replaces the earlier attempt',
            [run({ runId: 1, runAttempt: 2, conclusion: 'success' }), run({ runId: 1, conclusion: 'failure' })],
            [[1, 2]],
        ],
        [
            'a queued re-run has no start yet and still replaces the attempt before it',
            [
                run({ runId: 1, conclusion: 'failure' }),
                run({ runId: 1, runAttempt: 2, conclusion: null, startedAt: null }),
            ],
            [[1, 2]],
        ],
    ])('latestRunPerWorkflow: %s', (_, runs, expected) => {
        expect(latestRunPerWorkflow(runs).map((r) => [r.runId, r.runAttempt])).toEqual(expected)
    })

    test.each(['failure', 'timed_out', 'startup_failure', 'stale'])(
        'a matrix with a %s shard beside a passed one is failed',
        (conclusion) => {
            const shard = (id: number, shardConclusion: string): WorkflowJobApi =>
                ({
                    id,
                    run_id: 1,
                    name: `Jest (${id}/2)`,
                    status: 'completed',
                    conclusion: shardConclusion,
                    started_at: '2026-06-01T00:00:00Z',
                    completed_at: '2026-06-01T00:02:00Z',
                    duration_seconds: 120,
                    steps: [],
                }) as unknown as WorkflowJobApi
            const [workflow] = buildWorkflows([run({})], {
                'github_actions:1:1': [shard(1, 'success'), shard(2, conclusion)],
            })

            expect(workflow.items?.map((item) => item.status)).toEqual(['failure'])
        }
    )
})
