import { latestRunPerWorkflow } from './ciExplorerGraph'
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
    ])('latestRunPerWorkflow: %s', (_, runs, expected) => {
        expect(latestRunPerWorkflow(runs).map((r) => [r.runId, r.runAttempt])).toEqual(expected)
    })
})
