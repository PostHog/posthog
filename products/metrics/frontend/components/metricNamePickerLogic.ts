import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { metricsValuesRetrieve } from 'products/metrics/frontend/generated/api'
import type { _MetricNameApi } from 'products/metrics/frontend/generated/api.schemas'

import type { metricNamePickerLogicType } from './metricNamePickerLogicType'

export type MetricNameItem = _MetricNameApi

export const metricNamePickerLogic = kea<metricNamePickerLogicType>([
    path(['products', 'metrics', 'frontend', 'components', 'metricNamePickerLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
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
                    const response = await metricsValuesRetrieve(String(values.currentTeamId), {
                        value: values.search,
                        limit: 100,
                    })
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
