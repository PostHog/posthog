// What the Context tab compares: the selected workflow, matrix, job, or step against its recent runs on the
// default branch.

import type { CITimingContextApi, CITimingSampleApi } from '../generated/api.schemas'
import { CIEngine, statusLabel } from './ciExplorerDetails'
import { CIExplorerWorkflow, elapsedSeconds, jobsOf, resolveNode, workflowJobs } from './ciExplorerGraph'
import { githubJobUrl, githubRunUrl } from './github'

export type CIContextKind = 'workflow' | 'matrix' | 'job' | 'step'

export const CONTEXT_KIND_NAME: Record<CIContextKind, string> = {
    workflow: 'Workflow',
    matrix: 'Matrix',
    job: 'Job',
    step: 'Step',
}

export interface CIContextSelection {
    /** Identifies the selection, so an answer for an earlier selection is never shown for this one. */
    key: string
    label: string
    kind: CIContextKind
    engine: NonNullable<CIEngine>
    statusText: string
    /** Only a passed selection is compared with the average, which is an average of passed runs. */
    passed: boolean
    currentSeconds: number | null
    runId: number
    runAttempt: number
    jobIds: number[]
    stepNumber: number | null
}

/** The selection the Context tab describes, or null when nothing comparable is focused. */
export function contextSelection(
    workflows: CIExplorerWorkflow[],
    nodeId: string | null,
    stepNumber: number | null
): CIContextSelection | null {
    const node = resolveNode(workflows, nodeId)
    const run = node?.workflow.run
    if (!node || !run || run.runId === null || !run.ciEngine) {
        return null
    }
    const base = { engine: run.ciEngine, runId: run.runId, runAttempt: run.runAttempt ?? 1 }
    const selection = (
        kind: CIContextKind,
        label: string,
        conclusion: string | null,
        currentSeconds: number | null,
        jobIds: number[],
        step: number | null = null
    ): CIContextSelection => ({
        ...base,
        key: [base.engine, base.runId, base.runAttempt, kind, jobIds.join(','), step ?? ''].join(':'),
        label,
        kind,
        statusText: statusLabel(conclusion),
        passed: conclusion === 'success',
        currentSeconds,
        jobIds,
        stepNumber: step,
    })
    const { workflow, item, shard } = node
    if (!item) {
        // The average is measured from the first job start to the last job finish, so the current value is too.
        // The run's own duration also counts the wait for a runner.
        const executed = workflowJobs(workflow).filter(
            (job) => job.conclusion !== 'skipped' && job.conclusion !== 'neutral'
        )
        return selection(
            'workflow',
            run.workflow,
            run.conclusion,
            executed.length ? elapsedSeconds(executed) : null,
            []
        )
    }
    const job = shard?.job ?? (item.id === nodeId ? item.job : null)
    if (!job) {
        // A matrix has a status and no conclusion of its own. Running maps to none, as it does for a job.
        return selection(
            'matrix',
            item.name,
            item.status === 'running' ? null : item.status,
            item.durationSeconds,
            jobsOf(item).map((shardJob) => shardJob.id)
        )
    }
    const step = stepNumber === null ? undefined : job.steps.find((s) => s.number === stepNumber)
    if (step) {
        return selection('step', step.name, step.conclusion, step.duration_seconds, [job.id], step.number)
    }
    return selection('job', job.name, job.conclusion, job.duration_seconds, [job.id])
}

/**
 * How far the selection is from the average, in percent. Null when the two do not compare: the selection did
 * not pass, has no duration yet, or no passed run matched.
 */
export function deltaPercent(selection: CIContextSelection, context: CITimingContextApi): number | null {
    if (!selection.passed || selection.currentSeconds === null || !context.average_seconds) {
        return null
    }
    return Math.round((selection.currentSeconds / context.average_seconds - 1) * 100)
}

/** Where a matched run can be read at its source. Depot CI has no public page for a run, so that one stays in PostHog. */
export function sampleUrl(
    repoOwner: string,
    repoName: string,
    sample: CITimingSampleApi,
    postHogRunUrl: string
): { url: string; external: boolean } {
    if (sample.ci_engine === 'depot_ci') {
        return { url: postHogRunUrl, external: false }
    }
    return {
        url:
            sample.job_id === null
                ? `${githubRunUrl(repoOwner, repoName, sample.run_id)}/attempts/${sample.run_attempt}`
                : githubJobUrl(repoOwner, repoName, sample.run_id, sample.job_id, sample.step_number),
        external: true,
    }
}
