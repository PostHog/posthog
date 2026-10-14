// A pull request's activity in the order it happened: what people did to it, and the CI of each commit.

import { dayjs } from 'lib/dayjs'

import type { PRLifecycleApi, PRLifecycleEventApi, WorkflowRunDetailApi } from '../generated/api.schemas'
import { isDecisiveFailure } from './lifecycle'

// The commit rows carry the CI of the pull request, so the per-workflow start and finish events are left out.
export type CIActivityEventKind = Exclude<PRLifecycleEventApi['kind'], 'ci_started' | 'ci_finished'>

export interface CIActivityEvent {
    type: 'event'
    at: string
    kind: CIActivityEventKind
    /** Login of the person who did it, when the source says. */
    actor: string | null
}

export interface CIActivityCommit {
    type: 'commit'
    /** When the first run of the commit started. */
    at: string
    headSha: string
    /** A merge queue gate attempt, which tests a commit the queue made and not one the author pushed. */
    mergeQueue: boolean
    /** The newest commit the author pushed. */
    latest: boolean
    runs: number
    /** Runs that failed at any point, re-runs included. A count of history, not the commit's verdict. */
    failed: number
    /** First run start to last run update, re-runs and idle gaps included. Null while nothing has finished. */
    elapsedSeconds: number | null
}

export type CIActivityRow = CIActivityEvent | CIActivityCommit

export interface CIActivityDay {
    /** The calendar day, as YYYY-MM-DD. */
    date: string
    rows: CIActivityRow[]
}

function isActivityEvent(event: PRLifecycleEventApi): event is PRLifecycleEventApi & { kind: CIActivityEventKind } {
    return event.kind !== 'ci_started' && event.kind !== 'ci_finished'
}

/** One row per commit that has a started run. */
export function commitRows(prRuns: WorkflowRunDetailApi[]): CIActivityCommit[] {
    const bySha = new Map<string, WorkflowRunDetailApi[]>()
    for (const run of prRuns) {
        if (!run.run_started_at) {
            continue
        }
        const runs = bySha.get(run.head_sha)
        if (runs) {
            runs.push(run)
        } else {
            bySha.set(run.head_sha, [run])
        }
    }
    const rows = [...bySha.entries()].map(([headSha, runs]): CIActivityCommit => {
        const start = Math.min(...runs.map((run) => Date.parse(run.run_started_at as string)))
        const ends = runs
            .filter((run) => run.status === 'completed' && run.updated_at)
            .map((run) => Date.parse(run.updated_at as string))
        return {
            type: 'commit',
            at: new Date(start).toISOString(),
            headSha,
            mergeQueue: runs.every((run) => run.is_merge_queue),
            latest: false,
            runs: runs.length,
            failed: runs.filter((run) => isDecisiveFailure(run.conclusion)).length,
            elapsedSeconds: ends.length ? Math.max(0, Math.round((Math.max(...ends) - start) / 1000)) : null,
        }
    })
    const pushed = rows.filter((row) => !row.mergeQueue).sort((a, b) => b.at.localeCompare(a.at))[0]
    return rows.map((row) => ({ ...row, latest: row === pushed }))
}

/** The activity grouped by calendar day, oldest first. On a tie, what a person did comes before the CI it started. */
export function activityDays(lifecycle: PRLifecycleApi | null, commits: CIActivityCommit[]): CIActivityDay[] {
    const author = lifecycle?.pull_request.author.handle ?? null
    const events = (lifecycle?.events ?? []).filter(isActivityEvent).map(
        (event): CIActivityEvent => ({
            type: 'event',
            at: event.at,
            kind: event.kind,
            actor: event.kind === 'opened' ? author : (event.detail ?? null),
        })
    )
    const rows: CIActivityRow[] = [...events, ...commits].sort(
        (a, b) => Date.parse(a.at) - Date.parse(b.at) || Number(a.type === 'commit') - Number(b.type === 'commit')
    )
    const days: CIActivityDay[] = []
    for (const row of rows) {
        const date = dayjs(row.at).format('YYYY-MM-DD')
        if (days[days.length - 1]?.date !== date) {
            days.push({ date, rows: [] })
        }
        days[days.length - 1].rows.push(row)
    }
    return days
}
