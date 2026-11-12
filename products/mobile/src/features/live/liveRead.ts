import { type LiveQueryKey, liveQuery, liveWindow } from '@/api/live'
import { abortError } from '@/lib/abort'
import { isRecord } from '@/lib/records'
import {
    liveActivity,
    liveBreakdown,
    liveEvents,
    livePathCounts,
    livePathsMode,
    liveRankedRows,
    liveReferrerCounts,
    liveUsersOnlineFromQuery,
    liveWorld,
} from '@/model/adapters/live'
import type { LivePathsMode, LiveRankedRow, LiveSnapshot, LiveWorld } from '@/model/live'

import type { LiveReadResult } from './liveController'

const TOP_JOB: Record<LivePathsMode, LiveQueryKey> = { pages: 'paths', screens: 'screens' }

/** The web's jobs, the chart's first so a slow read fills the top of the screen first. */
function jobs(mode: LivePathsMode): LiveQueryKey[] {
    return ['usersPageviews', TOP_JOB[mode], 'referrer', 'device', 'browser', 'geo', 'recentEvents']
}
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
    const askedMode = livePathsMode(previous.activity)
    const keys = input.countUsersOnline ? [...jobs(askedMode), 'usersOnline' as const] : jobs(askedMode)
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
    let complete = answers.size === keys.length
    // The top list asks in the form the last read called for. When this read calls for the other form, as on an app
    // project's first read, it asks once more in that form, so the list never shows the wrong form for a whole interval.
    const mode = livePathsMode(activity)
    if (mode !== askedMode && !signal.aborted) {
        answers.delete(TOP_JOB[askedMode])
        try {
            const answer = await run(TOP_JOB[mode], liveQuery(TOP_JOB[mode], options), signal, now)
            if (answered(answer)) {
                answers.set(TOP_JOB[mode], answer)
            } else {
                complete = false
            }
        } catch {
            complete = false
        }
    }
    const topMode: LivePathsMode = answers.has('screens') ? 'screens' : 'pages'
    const topAnswer = answers.get(TOP_JOB[topMode])
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
            // Rank changes compare rows of one form only, so a switch between pages and screens shows no badges.
            topPages: topAnswer
                ? ranked(livePathCounts(topAnswer), previous.topPagesMode === topMode ? previous.topPages : null)
                : previous.topPages,
            topPagesMode: topAnswer ? topMode : previous.topPagesMode,
            topReferrers: part(
                'referrer',
                (answer) => ranked(liveReferrerCounts(answer), previous.topReferrers),
                previous.topReferrers
            ),
            devices: part('device', (answer) => liveBreakdown(answer, 'devices'), previous.devices),
            browsers: part('browser', (answer) => liveBreakdown(answer, 'browsers'), previous.browsers),
            countries: part('geo', (answer) => liveBreakdown(answer, 'countries'), previous.countries),
            world: part('geo', liveWorld, previous.world),
            events: part('recentEvents', liveEvents, previous.events),
            usersOnline: part('usersOnline', liveUsersOnlineFromQuery, previous.usersOnline),
        },
        complete,
    }
}

export interface LiveWorldReadInput {
    run: LiveQueryRunner
    now: number
    signal: AbortSignal
}

/** The countries screen's read: the `geo` job alone, so the screen never runs Live's full read. */
export async function readLiveWorld({ run, now, signal }: LiveWorldReadInput): Promise<LiveReadResult<LiveWorld>> {
    const answer = await run('geo', liveQuery('geo', { window: liveWindow(now), pathCleaning: false }), signal, now)
    if (!answered(answer)) {
        throw new Error('The geo query did not finish.')
    }
    return { data: liveWorld(answer), complete: true }
}
