import { MakeLogicType, actions, connect, kea, listeners, path, reducers } from 'kea'

import { dayjs } from 'lib/dayjs'
import posthog from 'lib/posthog-typed'

import { experimentsActivityRetrieve } from 'products/experiments/frontend/generated/api'
import { featureFlagsActivityRetrieve } from 'products/feature_flags/frontend/generated/api'
import type { ActivityLogEntryApi } from 'products/feature_flags/frontend/generated/api.schemas'
import { surveysActivityRetrieve } from 'products/surveys/frontend/generated/api'

import type { ActivityEntry } from './releaseChanges'
import { releaseLogic } from './releaseLogic'

const ACTIVITY_CONCURRENCY = 6
const ACTIVITY_PAGE_SIZE = 100
const ACTIVITY_MAX_PAGES = 5
const HISTORY_DAYS = 90

interface ReleaseCalendarLogicValues {
    currentProjectId: number | null
    expanded: Record<string, true>
    flagActivity: Record<number, ActivityLogEntryApi[]>
    failedFlagIds: number[]
    objectActivity: Record<string, ActivityEntry[]>
    failedObjectKeys: string[]
}

interface ReleaseCalendarLogicActions {
    toggleExpanded: (id: string) => { id: string }
    loadFlagActivity: (flagIds: number[]) => { flagIds: number[] }
    setFlagActivity: (
        flagId: number,
        entries: ActivityLogEntryApi[]
    ) => {
        flagId: number
        entries: ActivityLogEntryApi[]
    }
    setFlagActivityFailed: (flagId: number) => { flagId: number }
    refreshFlagActivity: (flagIds: number[]) => { flagIds: number[] }
    loadObjectActivity: (keys: string[]) => { keys: string[] }
    setObjectActivity: (key: string, entries: ActivityEntry[]) => { key: string; entries: ActivityEntry[] }
    setObjectActivityFailed: (key: string) => { key: string }
}

type releaseCalendarLogicType = MakeLogicType<ReleaseCalendarLogicValues, ReleaseCalendarLogicActions>

export const releaseCalendarLogic = kea<releaseCalendarLogicType>([
    path(['products', 'release', 'frontend', 'releaseCalendarLogic']),
    connect(() => ({ values: [releaseLogic, ['currentProjectId']] })),
    actions({
        toggleExpanded: (id: string) => ({ id }),
        loadFlagActivity: (flagIds: number[]) => ({ flagIds }),
        setFlagActivity: (flagId: number, entries: ActivityLogEntryApi[]) => ({ flagId, entries }),
        setFlagActivityFailed: (flagId: number) => ({ flagId }),
        refreshFlagActivity: (flagIds: number[]) => ({ flagIds }),
        loadObjectActivity: (keys: string[]) => ({ keys }),
        setObjectActivity: (key: string, entries: ActivityEntry[]) => ({ key, entries }),
        setObjectActivityFailed: (key: string) => ({ key }),
    }),
    reducers({
        expanded: [
            {} as Record<string, true>,
            {
                toggleExpanded: (state, { id }) => {
                    const { [id]: open, ...rest } = state
                    return open ? rest : { ...state, [id]: true as const }
                },
            },
        ],
        flagActivity: [
            {} as Record<number, ActivityLogEntryApi[]>,
            { setFlagActivity: (state, { flagId, entries }) => ({ ...state, [flagId]: entries }) },
        ],
        objectActivity: [
            {} as Record<string, ActivityEntry[]>,
            { setObjectActivity: (state, { key, entries }) => ({ ...state, [key]: entries }) },
        ],
        failedObjectKeys: [
            [] as string[],
            {
                setObjectActivityFailed: (state, { key }) => (state.includes(key) ? state : [...state, key]),
                setObjectActivity: (state, { key }) => state.filter((item) => item !== key),
                loadObjectActivity: (state, { keys }) => state.filter((item) => !keys.includes(item)),
            },
        ],
        failedFlagIds: [
            [] as number[],
            {
                setFlagActivityFailed: (state, { flagId }) => (state.includes(flagId) ? state : [...state, flagId]),
                setFlagActivity: (state, { flagId }) => state.filter((id) => id !== flagId),
                loadFlagActivity: (state, { flagIds }) => state.filter((id) => !flagIds.includes(id)),
            },
        ],
    }),
    listeners(({ actions, values, cache }) => {
        const fetchPage = (
            key: string,
            page: number,
            signal: AbortSignal
        ): Promise<{ results: ActivityEntry[]; next: string | null }> => {
            const projectId = String(values.currentProjectId)
            const [kind, id] = key.split(':')
            const params = { limit: ACTIVITY_PAGE_SIZE, page }
            if (kind === 'experiment') {
                return experimentsActivityRetrieve(projectId, Number(id), params, { signal })
            }
            if (kind === 'survey') {
                return surveysActivityRetrieve(projectId, id, params, { signal })
            }
            return featureFlagsActivityRetrieve(projectId, Number(id), params, { signal })
        }
        const fetchHistory = async (key: string, signal: AbortSignal): Promise<ActivityEntry[]> => {
            const since = dayjs().subtract(HISTORY_DAYS, 'day')
            const entries: ActivityEntry[] = []
            for (let page = 1; page <= ACTIVITY_MAX_PAGES; page++) {
                const response = await fetchPage(key, page, signal)
                entries.push(...response.results)
                const oldest = response.results[response.results.length - 1]
                if (!response.next || !oldest || dayjs(oldest.created_at).isBefore(since)) {
                    break
                }
            }
            return entries
        }
        const store = (key: string, entries: ActivityEntry[]): void => {
            if (key.startsWith('flag:')) {
                actions.setFlagActivity(Number(key.slice(5)), entries as ActivityLogEntryApi[])
            } else {
                actions.setObjectActivity(key, entries)
            }
        }
        const fail = (key: string): void => {
            if (key.startsWith('flag:')) {
                actions.setFlagActivityFailed(Number(key.slice(5)))
            } else {
                actions.setObjectActivityFailed(key)
            }
        }
        const pump = (): void => {
            while (cache.running < ACTIVITY_CONCURRENCY && cache.queue.length) {
                const key: string = cache.queue.shift()
                const signal: AbortSignal = cache.controller.signal
                const generation: number = cache.generations.get(key)
                cache.running += 1
                fetchHistory(key, signal)
                    .then(
                        (entries) => !signal.aborted && cache.generations.get(key) === generation && store(key, entries)
                    )
                    .catch(() => {
                        if (!signal.aborted && cache.generations.get(key) === generation) {
                            cache.requested.delete(key)
                            fail(key)
                        }
                    })
                    .finally(() => {
                        cache.running -= 1
                        if (!signal.aborted) {
                            pump()
                        }
                    })
            }
        }
        const enqueue = (keys: string[]): void => {
            cache.requested = cache.requested ?? new Set<string>()
            cache.queue = cache.queue ?? []
            cache.running = cache.running ?? 0
            cache.generations = cache.generations ?? new Map<string, number>()
            if (!cache.controller) {
                cache.disposables.add(
                    () => {
                        const controller = new AbortController()
                        cache.controller = controller
                        return () => {
                            controller.abort()
                            cache.queue = []
                        }
                    },
                    'flagHistory',
                    { pauseOnPageHidden: false }
                )
            }
            for (const key of keys) {
                if (!cache.requested.has(key)) {
                    cache.requested.add(key)
                    cache.generations.set(key, (cache.generations.get(key) ?? 0) + 1)
                    cache.queue.push(key)
                }
            }
            pump()
        }
        return {
            toggleExpanded: ({ id }) => {
                if (values.expanded[id]) {
                    posthog.capture('release row expanded', { release_id: id })
                }
            },
            refreshFlagActivity: ({ flagIds }) => {
                const requested = flagIds.filter((flagId) => cache.requested?.has(`flag:${flagId}`))
                for (const flagId of requested) {
                    cache.requested.delete(`flag:${flagId}`)
                }
                if (requested.length) {
                    actions.loadFlagActivity(requested)
                }
            },
            loadFlagActivity: ({ flagIds }) => {
                enqueue(flagIds.map((flagId) => `flag:${flagId}`))
            },
            loadObjectActivity: ({ keys }) => {
                enqueue(keys)
            },
        }
    }),
])
