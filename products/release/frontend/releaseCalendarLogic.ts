import { MakeLogicType, actions, connect, kea, listeners, path, reducers } from 'kea'

import { featureFlagsActivityRetrieve } from 'products/feature_flags/frontend/generated/api'
import type { ActivityLogEntryApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { releaseLogic } from './releaseLogic'

const ACTIVITY_CONCURRENCY = 6

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
    listeners(({ actions, values, cache }) => ({
        loadFlagActivity: async ({ flagIds }) => {
            cache.requested = cache.requested ?? new Set<number>()
            const todo = flagIds.filter((id) => !cache.requested.has(id))
            todo.forEach((id) => cache.requested.add(id))
            const projectId = String(values.currentProjectId)
            for (let start = 0; start < todo.length; start += ACTIVITY_CONCURRENCY) {
                await Promise.all(
                    todo.slice(start, start + ACTIVITY_CONCURRENCY).map(async (flagId) => {
                        try {
                            const page = await featureFlagsActivityRetrieve(projectId, flagId, { limit: 100 })
                            actions.setFlagActivity(flagId, page.results)
                        } catch {
                            actions.setFlagActivity(flagId, [])
                        }
                    })
                )
            }
        },
    })),
])
