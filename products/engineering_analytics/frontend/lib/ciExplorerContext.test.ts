import type { CITimingContextApi, WorkflowJobApi } from '../generated/api.schemas'
import { CIContextSelection, contextSelection, deltaPercent } from './ciExplorerContext'
import { buildWorkflows } from './ciExplorerGraph'
import type { WorkflowRun } from './lifecycle'

const RUN: WorkflowRun = {
    workflow: 'CI',
    workflowId: 7,
    ciEngine: 'github_actions',
    conclusion: 'failure',
    startedAt: '2026-06-01T00:00:00Z',
    finishedAt: '2026-06-01T00:10:00Z',
    durationSeconds: 600,
    runId: 42,
    runAttempt: 3,
}
const WORKFLOW = 'github_actions:42:3'

function job(id: number, name: string, conclusion: string): WorkflowJobApi {
    return {
        id,
        run_id: 42,
        name,
        status: 'completed',
        conclusion,
        started_at: '2026-06-01T00:00:00Z',
        completed_at: '2026-06-01T00:02:00Z',
        duration_seconds: 120,
        runner_provider: 'self_hosted',
        runner_label: 'depot-ubuntu-latest',
        estimated_cost_usd: null,
        ci_engine: 'github_actions',
        steps: [
            {
                number: 4,
                name: 'Run tests',
                status: 'completed',
                conclusion: 'success',
                started_at: null,
                completed_at: null,
                duration_seconds: 90,
            },
        ],
    }
}

const WORKFLOWS = buildWorkflows([RUN], {
    [WORKFLOW]: [job(1, 'Jest (1/2)', 'success'), job(2, 'Jest (2/2)', 'failure'), job(3, 'Lint', 'success')],
})

describe('ciExplorerContext', () => {
    test.each<[string, string, number | null, Partial<CIContextSelection>]>([
        ['a workflow', WORKFLOW, null, { kind: 'workflow', jobIds: [], runAttempt: 3, passed: false }],
        ['a matrix asks about every shard', `${WORKFLOW}/Jest`, null, { kind: 'matrix', passed: false }],
        ['a shard', `${WORKFLOW}/Jest/1`, null, { kind: 'job', jobIds: [1], passed: true }],
        [
            'a step of the focused job',
            `${WORKFLOW}/Lint`,
            4,
            { kind: 'step', jobIds: [3], stepNumber: 4, currentSeconds: 90 },
        ],
        ['a step the job does not have falls back to the job', `${WORKFLOW}/Lint`, 9, { kind: 'job', jobIds: [3] }],
    ])('contextSelection: %s', (_, nodeId, stepNumber, expected) => {
        expect(contextSelection(WORKFLOWS, nodeId, stepNumber)).toMatchObject(expected)
    })

    it('asks about every shard of a matrix', () => {
        expect(contextSelection(WORKFLOWS, `${WORKFLOW}/Jest`, null)?.jobIds.sort()).toEqual([1, 2])
    })

    test.each<[string, Partial<CIContextSelection>, number | null, number | null]>([
        ['a passed selection is compared', { passed: true, currentSeconds: 120 }, 100, 20],
        [
            'a failed selection is not, because the average is of passed runs',
            { passed: false, currentSeconds: 120 },
            100,
            null,
        ],
        ['a running selection is not', { passed: true, currentSeconds: null }, 100, null],
        ['no matching passed run means no comparison', { passed: true, currentSeconds: 120 }, null, null],
    ])('deltaPercent: %s', (_, selection, averageSeconds, expected) => {
        expect(
            deltaPercent(selection as CIContextSelection, { average_seconds: averageSeconds } as CITimingContextApi)
        ).toBe(expected)
    })
})
