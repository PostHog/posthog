// Collapses a PR's raw lifecycle events (opened, ci_started, ci_finished, merged, closed — dozens per
// PR) into the facts the drill-in panel renders: milestones plus a verdict rollup.

import type { PRLifecycleEventApi } from '../generated/api.schemas'

export interface WorkflowVerdict {
    workflow: string
    conclusion: string
    at: string
}

export interface LifecycleSummary {
    openedAt: string | null
    firstCiStartedAt: string | null
    lastCiFinishedAt: string | null
    mergedAt: string | null
    closedAt: string | null
    /** Completed runs whose conclusion was not a pass — the rows worth listing. */
    notPassing: WorkflowVerdict[]
    passed: number
    /** Runs that started but never reported a finish — queued or in progress. */
    unsettled: number
}

export interface WorkflowRun {
    workflow: string
    /** Null while the run hasn't reported a finish — queued or in progress. */
    conclusion: string | null
    startedAt: string | null
    finishedAt: string | null
    durationSeconds: number | null
    /** GitHub Actions run id — links straight to the run page when present. */
    runId: number | null
    /** Re-run attempt (1 for the first); null when unknown (lifecycle events don't carry it). */
    runAttempt: number | null
}

const PASSING_CONCLUSIONS = new Set(['success', 'skipped', 'neutral', 'completed'])

/** For a finished run's conclusion; 'completed' stands in when no conclusion was recorded. */
export function isPassingConclusion(conclusion: string): boolean {
    return PASSING_CONCLUSIONS.has(conclusion)
}

/** A decisive failure — the verdict that turns a run red. Cancelled/skipped/neutral are not failures. */
export function isDecisiveFailure(conclusion: string | null): boolean {
    return conclusion === 'failure' || conclusion === 'timed_out'
}

/**
 * ci_finished detail is "workflow name: conclusion" (the name may contain ": "), flattened by the API
 * from structured backend fields.
 * TODO: expose workflow/conclusion as structured fields on PRLifecycleEventApi and delete this parse.
 */
function parseFinishedDetail(detail: string | null | undefined): { workflow: string; conclusion: string | null } {
    if (!detail) {
        return { workflow: 'unknown workflow', conclusion: null }
    }
    const splitAt = detail.lastIndexOf(': ')
    if (splitAt === -1) {
        return { workflow: detail, conclusion: null }
    }
    return { workflow: detail.slice(0, splitAt), conclusion: detail.slice(splitAt + 2) }
}

/**
 * Pairs ci_started / ci_finished events into per-workflow runs with durations, FIFO by workflow name.
 * A finish without a matching start (events outside the window) still yields a row.
 */
export function workflowRuns(events: PRLifecycleEventApi[]): WorkflowRun[] {
    const runs: WorkflowRun[] = []
    const unfinishedByWorkflow = new Map<string, WorkflowRun[]>()

    for (const event of events) {
        if (event.kind === 'ci_started') {
            const workflow = event.detail ?? 'unknown workflow'
            const run: WorkflowRun = {
                workflow,
                conclusion: null,
                startedAt: event.at,
                finishedAt: null,
                durationSeconds: null,
                runId: event.run_id ?? null,
                runAttempt: null,
            }
            runs.push(run)
            const queue = unfinishedByWorkflow.get(workflow) ?? []
            queue.push(run)
            unfinishedByWorkflow.set(workflow, queue)
        } else if (event.kind === 'ci_finished') {
            const { workflow, conclusion } = parseFinishedDetail(event.detail)
            const started = unfinishedByWorkflow.get(workflow)?.shift()
            if (started) {
                started.conclusion = conclusion ?? 'completed'
                started.finishedAt = event.at
                started.durationSeconds = Math.max(
                    0,
                    Math.round((Date.parse(event.at) - Date.parse(started.startedAt as string)) / 1000)
                )
            } else {
                runs.push({
                    workflow,
                    conclusion: conclusion ?? 'completed',
                    startedAt: null,
                    finishedAt: event.at,
                    durationSeconds: null,
                    runId: event.run_id ?? null,
                    runAttempt: null,
                })
            }
        }
    }

    return runs
}

export function summarizeLifecycle(events: PRLifecycleEventApi[]): LifecycleSummary {
    const summary: LifecycleSummary = {
        openedAt: null,
        firstCiStartedAt: null,
        lastCiFinishedAt: null,
        mergedAt: null,
        closedAt: null,
        notPassing: [],
        passed: 0,
        unsettled: 0,
    }
    let started = 0
    let finished = 0

    for (const event of events) {
        switch (event.kind) {
            case 'opened':
                summary.openedAt = event.at
                break
            case 'merged':
                summary.mergedAt = event.at
                break
            case 'closed':
                summary.closedAt = event.at
                break
            case 'ci_started':
                started += 1
                if (!summary.firstCiStartedAt || event.at < summary.firstCiStartedAt) {
                    summary.firstCiStartedAt = event.at
                }
                break
            case 'ci_finished': {
                finished += 1
                if (!summary.lastCiFinishedAt || event.at > summary.lastCiFinishedAt) {
                    summary.lastCiFinishedAt = event.at
                }
                const { workflow, conclusion } = parseFinishedDetail(event.detail)
                if (conclusion === null || PASSING_CONCLUSIONS.has(conclusion)) {
                    summary.passed += 1
                } else {
                    summary.notPassing.push({ workflow, conclusion, at: event.at })
                }
                break
            }
        }
    }

    summary.unsettled = Math.max(0, started - finished)
    return summary
}
