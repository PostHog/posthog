// One push (head SHA) collapsed into a CI round: when it started, wall-clock CI time, verdict.
// Mirrors the backend's push-history rule (pull_request_list.py): the latest run per workflow
// decides the verdict; wall time is the earliest run start → the latest completed run end.

import type { PushCISampleApi } from '../generated/api.schemas'
import { WorkflowRun, isDecisiveFailure } from './lifecycle'
import { VERDICT_COLOR } from './runStatus'

export interface PushRound {
    headSha: string
    startedAt: string | null
    /** Earliest run start → latest completed run end; null while nothing has completed. */
    wallSeconds: number | null
    failed: boolean
    pending: boolean
}

export function pushRoundFromSample(sample: PushCISampleApi): PushRound {
    return {
        headSha: sample.head_sha,
        startedAt: sample.started_at,
        wallSeconds: sample.wall_seconds,
        failed: sample.failed,
        pending: sample.pending,
    }
}

/** Collapse one push's runs into a round, client-side (the PR page already has the runs). */
export function pushRoundOf(headSha: string, runs: WorkflowRun[]): PushRound {
    const latestByWorkflow = new Map<string, WorkflowRun>()
    for (const run of runs) {
        const seen = latestByWorkflow.get(run.workflow)
        if (!seen || (run.startedAt ?? '') > (seen.startedAt ?? '')) {
            latestByWorkflow.set(run.workflow, run)
        }
    }
    const latest = [...latestByWorkflow.values()]
    const starts = runs.map((run) => run.startedAt).filter((at): at is string => !!at)
    const ends = runs.map((run) => run.finishedAt).filter((at): at is string => !!at)
    const startedAt = starts.length ? starts.reduce((min, at) => (at < min ? at : min)) : null
    const lastEnd = ends.length ? ends.reduce((max, at) => (at > max ? at : max)) : null
    return {
        headSha,
        startedAt,
        wallSeconds:
            startedAt && lastEnd ? Math.max(0, Math.round((Date.parse(lastEnd) - Date.parse(startedAt)) / 1000)) : null,
        failed: latest.some((run) => isDecisiveFailure(run.conclusion)),
        pending: latest.some((run) => run.conclusion === null),
    }
}

/** Status color for a round: a decisive failure wins, then still-running amber, then green. */
export function pushRoundColor(round: PushRound): string {
    return round.failed ? VERDICT_COLOR.danger : round.pending ? VERDICT_COLOR.warning : VERDICT_COLOR.success
}

export function pushRoundVerdictLabel(round: PushRound): string {
    if (round.failed) {
        return round.pending ? 'failing · still running' : 'failed'
    }
    return round.pending ? 'running' : 'passed'
}
