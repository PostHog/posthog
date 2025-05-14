import { actions, kea, path, props, reducers, selectors } from 'kea'
import api from 'lib/api'
import { loaders } from 'node_modules/kea-loaders/lib'

import type { visionHogHistoryLogicType } from './visionHogHistoryLogicType'

export interface VisionHogHistoryLogicProps {
    // Define any props your logic might need here
}

export const visionHogHistoryLogic = kea<visionHogHistoryLogicType>([
    path(['products', 'visionHog', 'frontend', 'visionHogHistoryLogic']),
    props({} as VisionHogHistoryLogicProps),

    loaders({
        events: [
            [] as any[],
            {
                loadEvents: async () => {
                    const response = await api.events.list()
                    return response.results
                },
            },
        ],
    }),

    reducers({
        filters: [
            { eventType: null },
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
    }),

    actions({
        setFilters: (filters) => ({ filters }),
    }),

    selectors({
        filteredEvents: [
            (s) => [s.events, s.filters],
            (events, filters) => {
                if (!filters.eventType) {
                    return events
                }
                return events.filter((event) => event.event === filters.eventType)
            },
        ],
    }),
])
