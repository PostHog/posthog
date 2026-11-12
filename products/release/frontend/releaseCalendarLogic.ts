import { MakeLogicType, actions, connect, kea, listeners, path, reducers } from 'kea'

import { dayjs } from 'lib/dayjs'

import { featureFlagsActivityRetrieve } from 'products/feature_flags/frontend/generated/api'
import type { ActivityLogEntryApi } from 'products/feature_flags/frontend/generated/api.schemas'

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
        const fetchHistory = async (flagId: number, signal: AbortSignal): Promise<ActivityLogEntryApi[]> => {
            const projectId = String(values.currentProjectId)
            const since = dayjs().subtract(HISTORY_DAYS, 'day')
            const entries: ActivityLogEntryApi[] = []
            for (let page = 1; page <= ACTIVITY_MAX_PAGES; page++) {
                const response = await featureFlagsActivityRetrieve(
                    projectId,
                    flagId,
                    { limit: ACTIVITY_PAGE_SIZE, page },
                    { signal }
                )
                entries.push(...response.results)
                const oldest = response.results[response.results.length - 1]
                if (!response.next || !oldest || dayjs(oldest.created_at).isBefore(since)) {
                    break
                }
            }
            return entries
        }
        const pump = (): void => {
            while (cache.running < ACTIVITY_CONCURRENCY && cache.queue.length) {
                const flagId: number = cache.queue.shift()
                const signal: AbortSignal = cache.controller.signal
                const generation: number = cache.generations.get(flagId)
                cache.running += 1
                fetchHistory(flagId, signal)
                    .then(
                        (entries) =>
                            !signal.aborted &&
                            cache.generations.get(flagId) === generation &&
                            actions.setFlagActivity(flagId, entries)
                    )
                    .catch(() => {
                        if (!signal.aborted && cache.generations.get(flagId) === generation) {
                            cache.requested.delete(flagId)
                            actions.setFlagActivityFailed(flagId)
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
        return {
            refreshFlagActivity: ({ flagIds }) => {
                for (const flagId of flagIds) {
                    cache.requested?.delete(flagId)
                }
                actions.loadFlagActivity(flagIds)
            },
            loadFlagActivity: ({ flagIds }) => {
                cache.requested = cache.requested ?? new Set<number>()
                cache.queue = cache.queue ?? []
                cache.running = cache.running ?? 0
                cache.generations = cache.generations ?? new Map<number, number>()
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
                for (const flagId of flagIds) {
                    if (!cache.requested.has(flagId)) {
                        cache.requested.add(flagId)
                        cache.generations.set(flagId, (cache.generations.get(flagId) ?? 0) + 1)
                        cache.queue.push(flagId)
                    }
                }
                pump()
            },
        }
    }),
])
