import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { metricNamePickerLogicType } from './metricNamePickerLogicType'

export interface MetricNameItem {
    name: string
    metric_type: string
}

export const metricNamePickerLogic = kea<metricNamePickerLogicType>([
    path(['products', 'metrics', 'frontend', 'components', 'metricNamePickerLogic']),
    actions({
        setSearch: (search: string) => ({ search }),
    }),
    reducers({
        search: ['' as string, { setSearch: (_, { search }) => search }],
    }),
    loaders(({ values }) => ({
        items: [
            [] as MetricNameItem[],
            {
                loadItems: async (_, breakpoint) => {
                    // Debounce — match the 300ms cadence used in the viewer logic so
                    // both fetches feel cohesive.
                    await breakpoint(300)
                    const response = await api.metrics.values({ search: values.search, limit: 100 })
                    breakpoint()
                    return response.results
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        setSearch: () => {
            actions.loadItems({})
        },
    })),
    afterMount(({ actions }) => {
        // Prime the list so the dropdown isn't empty on first open. Mirrors
        // serviceFilterLogic's afterMount in logs.
        actions.loadItems({})
    }),
])
