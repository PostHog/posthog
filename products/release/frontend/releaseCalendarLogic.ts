import { MakeLogicType, actions, connect, kea, listeners, path, reducers } from 'kea'

import { dayjs } from 'lib/dayjs'

import { featureFlagsActivityRetrieve } from 'products/feature_flags/frontend/generated/api'
import type { ActivityLogEntryApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { releaseLogic } from './releaseLogic'
import { CALENDAR_DAYS_BEFORE } from './releaseUtils'

const ACTIVITY_CONCURRENCY = 6
const ACTIVITY_PAGE_SIZE = 100
const ACTIVITY_MAX_PAGES = 5

interface ReleaseCalendarLogicValues {
    currentProjectId: number | null
    expanded: Record<string, true>
    flagActivity: Record<number, ActivityLogEntryApi[]>
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
}

type releaseCalendarLogicType = MakeLogicType<ReleaseCalendarLogicValues, ReleaseCalendarLogicActions>

export const releaseCalendarLogic = kea<releaseCalendarLogicType>([
    path(['products', 'release', 'frontend', 'releaseCalendarLogic']),
    connect(() => ({ values: [releaseLogic, ['currentProjectId']] })),
    actions({
        toggleExpanded: (id: string) => ({ id }),
        loadFlagActivity: (flagIds: number[]) => ({ flagIds }),
        setFlagActivity: (flagId: number, entries: ActivityLogEntryApi[]) => ({ flagId, entries }),
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
    }),
    listeners(({ actions, values, cache }) => {
        const fetchHistory = async (flagId: number): Promise<ActivityLogEntryApi[]> => {
            const projectId = String(values.currentProjectId)
            const since = dayjs().subtract(CALENDAR_DAYS_BEFORE, 'day')
            const entries: ActivityLogEntryApi[] = []
            for (let page = 1; page <= ACTIVITY_MAX_PAGES; page++) {
                const response = await featureFlagsActivityRetrieve(projectId, flagId, {
                    limit: ACTIVITY_PAGE_SIZE,
                    page,
                })
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
                cache.running += 1
                fetchHistory(flagId)
                    .then((entries) => actions.setFlagActivity(flagId, entries))
                    .catch(() => cache.requested.delete(flagId))
                    .finally(() => {
                        cache.running -= 1
                        pump()
                    })
            }
        }
        return {
            loadFlagActivity: ({ flagIds }) => {
                cache.requested = cache.requested ?? new Set<number>()
                cache.queue = cache.queue ?? []
                cache.running = cache.running ?? 0
                for (const flagId of flagIds) {
                    if (!cache.requested.has(flagId)) {
                        cache.requested.add(flagId)
                        cache.queue.push(flagId)
                    }
                }
                pump()
            },
        }
    }),
])
