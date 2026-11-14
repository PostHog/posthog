import { type LiveQueryKey, liveQuery, liveWindow } from '@/api/live'
import { abortError } from '@/lib/abort'
import { isRecord } from '@/lib/records'
import {
    liveActivity,
    liveBreakdown,
    liveEvents,
    livePathCounts,
    livePathsMode,
    livePathTotal,
    liveRankedRows,
    liveReferrerCounts,
    liveUsersOnlineFromQuery,
    liveWorld,
} from '@/model/adapters/live'
import type {
    LiveMobileMetrics,
    LivePathsMode,
    LiveProjectProfile,
    LiveRankedRow,
    LiveSnapshot,
    LiveWorld,
} from '@/model/live'

import type { LiveReadResult } from './liveController'

const TOP_JOB: Record<LivePathsMode, LiveQueryKey> = { pages: 'paths', screens: 'screens' }

/**
 * The web's jobs, the chart's first. The top list (`paths` or `screens`) runs after them, so it can take its form from
 * this read's activity.
 */
const JOBS: readonly LiveQueryKey[] = ['usersPageviews', 'referrer', 'device', 'browser', 'geo', 'recentEvents']
/** The Views queue's limit, so one read never holds more than two server queries at a time. */
const CONCURRENCY = 2

export type LiveQueryRunner = (
    key: LiveQueryKey,
    query: Record<string, unknown>,
    signal: AbortSignal,
    now: number
) => Promise<unknown>

export interface LiveReadInput {
    profile?: LiveProjectProfile
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
    const profile = input.profile ?? previous.profile ?? { kind: 'unknown' }
    const mobile = profile.kind === 'mobile' || profile.kind === 'mixed'
    const jobs = profile.kind === 'mobile' ? JOBS.filter((key) => key !== 'browser' && key !== 'referrer') : [...JOBS]
    if (mobile) {
        jobs.push('platforms', 'mobileSessions')
        if (profile.kind === 'mixed') jobs.push('screens')
    }
    const keys: LiveQueryKey[] = input.countUsersOnline ? [...jobs, 'usersOnline'] : [...jobs]
    const options = {
        window: liveWindow(now),
        pathCleaning: input.pathCleaning,
        mobileOnly: profile.kind === 'mobile',
        webOnly: profile.kind === 'web',
    }
    const ask = (key: LiveQueryKey): Promise<unknown> =>
        run(
            key,
            liveQuery(key, { ...options, mobileOnly: options.mobileOnly || (key === 'screens' && mobile) }),
            signal,
            now
        )
    let activityAnswer: Promise<unknown> | null = null
    let topMode: LivePathsMode = 'pages'
    const askTop = async (): Promise<unknown> => {
        // The activity job started first, so it has usually answered by now. When it failed, the last activity decides.
        const answer = await activityAnswer?.catch(() => undefined)
        topMode =
            profile.kind === 'mobile'
                ? 'screens'
                : profile.kind === 'mixed' || profile.kind === 'web'
                  ? 'pages'
                  : livePathsMode(answered(answer) ? liveActivity(answer, now) : previous.activity)
        return ask(TOP_JOB[topMode])
    }
    const settled = await settleInTurn(
        [
            ...keys.map((key) => (): Promise<unknown> => {
                const answer = ask(key)
                if (key === 'usersPageviews') {
                    activityAnswer = answer
                }
                return answer
            }),
            askTop,
        ],
        signal
    )
    const answers = new Map<LiveQueryKey, unknown>()
    let failure: unknown = null
    for (const [index, key] of [...keys, TOP_JOB[topMode]].entries()) {
        const result = settled[index]
        if (result?.status === 'fulfilled' && answered(result.value)) {
            answers.set(key, result.value)
        } else {
            failure ??= result?.status === 'rejected' ? result.reason : new Error(`The ${key} query did not finish.`)
        }
    }
    if (answers.size === 0) {
        throw failure ?? new Error('The live read failed.')
    }

    const activity = answers.has('usersPageviews')
        ? liveActivity(answers.get('usersPageviews'), now)
        : previous.activity
    const topAnswer = answers.get(TOP_JOB[topMode])
    const ranked = (counts: Map<string, number>, before: LiveRankedRow[] | null): LiveRankedRow[] => {
        // Shares are of the window's pageviews; without them, of the listed views, so they never read 0%.
        const listed = [...counts.values()].reduce((sum, views) => sum + views, 0)
        return liveRankedRows(
            counts,
            (topMode === 'screens' ? activity?.screenviews : activity?.pageviews) || listed,
            before
        )
    }
    const part = <T>(key: LiveQueryKey, build: (answer: unknown) => T, kept: T): T =>
        answers.has(key) ? build(answers.get(key)) : kept

    return {
        data: {
            profile,
            topScreens:
                profile.kind === 'mixed'
                    ? part(
                          'screens',
                          (answer) =>
                              liveRankedRows(
                                  livePathCounts(answer),
                                  livePathTotal(answer) ??
                                      [...livePathCounts(answer).values()].reduce((a, b) => a + b, 0),
                                  previous.topScreens ?? null
                              ),
                          previous.topScreens ?? null
                      )
                    : previous.topScreens,
            platforms: part('platforms', (answer) => liveBreakdown(answer, 'platforms'), previous.platforms ?? null),
            mobileMetrics: mobile
                ? liveSessionMetrics(answers.get('mobileSessions'), previous.mobileMetrics)
                : previous.mobileMetrics,
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
        complete: answers.size === keys.length + 1,
    }
}

export interface LiveWorldReadInput {
    webOnly?: boolean
    mobileOnly?: boolean
    run: LiveQueryRunner
    now: number
    signal: AbortSignal
}

/** The countries screen's read: the `geo` job alone, so the screen never runs Live's full read. */
export async function readLiveWorld({
    run,
    now,
    signal,
    mobileOnly,
    webOnly,
}: LiveWorldReadInput): Promise<LiveReadResult<LiveWorld>> {
    const answer = await run(
        'geo',
        liveQuery('geo', { window: liveWindow(now), pathCleaning: false, mobileOnly, webOnly }),
        signal,
        now
    )
    if (!answered(answer)) {
        throw new Error('The geo query did not finish.')
    }
    return { data: liveWorld(answer), complete: true }
}

function metricNumber(value: unknown): number | null {
    const number = typeof value === 'string' ? Number(value) : value
    return typeof number === 'number' && Number.isFinite(number) ? number : null
}

export function liveMobileMetrics(response: unknown, now: number): LiveMobileMetrics {
    const row =
        isRecord(response) && Array.isArray(response.results) && Array.isArray(response.results[0])
            ? response.results[0]
            : null
    if (!row || row.length < 5) throw new Error('The mobile metrics query did not finish.')
    const installsTracked = Number(row[3]) > 0
    return {
        dailyActiveUsers: metricNumber(row[0]),
        weeklyActiveUsers: metricNumber(row[1]),
        installs: installsTracked ? metricNumber(row[2]) : null,
        weeklyInstalls: installsTracked ? metricNumber(row[3]) : null,
        sessions: null,
        updatedAt: isRecord(response) && typeof response.liveFetchedAt === 'number' ? response.liveFetchedAt : now,
    }
}

function liveSessionMetrics(
    response: unknown,
    previous: LiveMobileMetrics | null | undefined
): LiveMobileMetrics | null {
    const row =
        isRecord(response) && Array.isArray(response.results) && Array.isArray(response.results[0])
            ? response.results[0]
            : null
    if (!row) return previous ?? null
    return {
        dailyActiveUsers: previous?.dailyActiveUsers ?? null,
        weeklyActiveUsers: previous?.weeklyActiveUsers ?? null,
        installs: previous?.installs ?? null,
        weeklyInstalls: previous?.weeklyInstalls ?? null,
        updatedAt: previous?.updatedAt ?? 0,
        sessions: Number(row[1]) > 0 ? metricNumber(row[0]) : null,
    }
}
