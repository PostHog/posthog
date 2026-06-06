import equal from 'fast-deep-equal'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { LogsFiltersHistoryEntry } from '../../../types'
import type { logsFilterHistoryLogicType } from './logsFilterHistoryLogicType'

export interface LogsFilterHistoryLogicProps {
    id: string
}

export const logsFilterHistoryLogic = kea<logsFilterHistoryLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'Filters', 'logsFilterHistoryLogic']),
    props({} as LogsFilterHistoryLogicProps),
    key((props) => props.id),
    connect((props: LogsFilterHistoryLogicProps) => ({
        actions: [logsViewerFiltersLogic({ id: props.id }), ['setFilters']],
    })),
    actions({
        pushToFilterHistory: (filters: LogsViewerFilters) => ({ filters }),
        restoreFiltersFromHistory: (index: number) => ({ index }),
        clearFilterHistory: true,
    }),
    reducers({
        filterHistory: [
            [] as LogsFiltersHistoryEntry[],
            { persist: true },
            {
                pushToFilterHistory: (state, { filters }) => {
                    if (state.length > 0 && equal(state[0].filters, filters)) {
                        return state
                    }
                    const entry: LogsFiltersHistoryEntry = { filters, timestamp: Date.now() }
                    return [entry, ...state].slice(0, 10)
                },
                clearFilterHistory: () => [],
            },
        ],
    }),
    selectors({
        hasFilterHistory: [
            (s) => [s.filterHistory],
            (filterHistory: LogsFiltersHistoryEntry[]) => filterHistory.length > 0,
        ],
    }),
    listeners(({ values, actions }) => ({
        restoreFiltersFromHistory: ({ index }) => {
            const entry = values.filterHistory[index]
            if (entry) {
                posthog.capture('logs filter history restored', {
                    history_index: index,
                    history_size: values.filterHistory.length,
                })
                actions.setFilters(entry.filters, false)
            }
        },
        clearFilterHistory: () => {
            posthog.capture('logs filter history cleared', {
                history_size: values.filterHistory.length,
            })
        },
    })),
])
