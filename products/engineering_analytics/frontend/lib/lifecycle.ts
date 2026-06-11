// Collapses a PR's raw lifecycle events (opened, ci_started, ci_finished, merged,
// closed — one pair per workflow run, so dozens per PR) into the few facts the
// drill-in panel renders: milestones plus a verdict rollup with failures called out.

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

const PASSING_CONCLUSIONS = new Set(['success', 'skipped', 'neutral'])

/** ci_finished detail is "workflow name: conclusion"; the name itself may contain ": ". */
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
