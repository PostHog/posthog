import { type LiveQueryKey, liveQuery, liveWindow } from '@/api/live'
import { abortError } from '@/lib/abort'
import { isRecord } from '@/lib/records'
import {
    liveActivity,
    liveBreakdown,
    liveEvents,
    livePathCounts,
    liveRankedRows,
    liveReferrerCounts,
    liveUsersOnlineFromQuery,
} from '@/model/adapters/live'
import type { LiveRankedRow, LiveSnapshot } from '@/model/live'

import type { LiveReadResult } from './liveController'

/** The web's jobs, the chart's first so a slow read fills the top of the screen first. */
const JOBS: readonly LiveQueryKey[] = [
    'usersPageviews',
    'paths',
    'referrer',
    'device',
    'browser',
    'geo',
    'recentEvents',
]
/** The Views queue's limit, so one read never holds more than two server queries at a time. */
const CONCURRENCY = 2

export type LiveQueryRunner = (
    key: LiveQueryKey,
    query: Record<string, unknown>,
    signal: AbortSignal,
    now: number
) => Promise<unknown>

export interface LiveReadInput {
    run: LiveQueryRunner
    previous: LiveSnapshot
    /** True when the live events service cannot count users online, so the read counts them with HogQL. */
    countUsersOnline: boolean
    pathCleaning: boolean
    now: number
    signal: AbortSignal
}

async function settleInTurn(
    tasks: readonly (() => Promise<unknown>)[],
    signal: AbortSignal
): Promise<PromiseSettledResult<unknown>[]> {
    const results: PromiseSettledResult<unknown>[] = new Array(tasks.length)
    let next = 0
    const worker = async (): Promise<void> => {
        while (next < tasks.length) {
            const index = next
            next += 1
            const task = tasks[index]
            try {
                if (signal.aborted || !task) {
                    throw abortError()
                }
                results[index] = { status: 'fulfilled', value: await task() }
            } catch (reason) {
                results[index] = { status: 'rejected', reason }
            }
        }
    }
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, tasks.length) }, worker))
    return results
}

/** A response that is still running carries no results; it counts as a failed job. */
function answered(value: unknown): boolean {
    return isRecord(value) && Array.isArray(value.results)
}

/**
 * Runs every job and builds the next snapshot. A failed job keeps its part's last value, and the read rejects only when
 * every job failed.
 */
export async function readLiveSnapshot(input: LiveReadInput): Promise<LiveReadResult<LiveSnapshot>> {
    const { run, previous, now, signal } = input
    const keys: LiveQueryKey[] = input.countUsersOnline ? [...JOBS, 'usersOnline'] : [...JOBS]
    const options = { window: liveWindow(now), pathCleaning: input.pathCleaning }
    const settled = await settleInTurn(
        keys.map((key) => () => run(key, liveQuery(key, options), signal, now)),
        signal
    )
    const answers = new Map<LiveQueryKey, unknown>()
    let failure: unknown = null
    keys.forEach((key, index) => {
        const result = settled[index]
        if (result?.status === 'fulfilled' && answered(result.value)) {
            answers.set(key, result.value)
        } else {
            failure ??= result?.status === 'rejected' ? result.reason : new Error(`The ${key} query did not finish.`)
        }
    })
    if (answers.size === 0) {
        throw failure ?? new Error('The live read failed.')
    }

    const activity = answers.has('usersPageviews')
        ? liveActivity(answers.get('usersPageviews'), now)
        : previous.activity
    const ranked = (counts: Map<string, number>, before: LiveRankedRow[] | null): LiveRankedRow[] => {
        // Shares are of the window's pageviews; without them, of the listed views, so they never read 0%.
        const listed = [...counts.values()].reduce((sum, views) => sum + views, 0)
        return liveRankedRows(counts, activity?.pageviews || listed, before)
    }
    const part = <T>(key: LiveQueryKey, build: (answer: unknown) => T, kept: T): T =>
        answers.has(key) ? build(answers.get(key)) : kept

    return {
        data: {
            activity,
            topPages: part('paths', (answer) => ranked(livePathCounts(answer), previous.topPages), previous.topPages),
            topReferrers: part(
                'referrer',
                (answer) => ranked(liveReferrerCounts(answer), previous.topReferrers),
                previous.topReferrers
            ),
            devices: part('device', (answer) => liveBreakdown(answer, 'devices'), previous.devices),
            browsers: part('browser', (answer) => liveBreakdown(answer, 'browsers'), previous.browsers),
            countries: part('geo', (answer) => liveBreakdown(answer, 'countries'), previous.countries),
            events: part('recentEvents', liveEvents, previous.events),
            usersOnline: part('usersOnline', liveUsersOnlineFromQuery, previous.usersOnline),
        },
        complete: answers.size === keys.length,
    }
}
