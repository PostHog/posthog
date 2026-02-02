import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import { FilterLogicalOperator } from '~/types'

import { LogsViewerConfig, LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'

import type { logsViewerConfigLogicType } from './logsViewerConfigLogicType'

export const DEFAULT_LOGS_VIEWER_CONFIG: LogsViewerConfig = {
    filters: {
        dateRange: { date_from: '-1h', date_to: null },
        searchTerm: '',
        severityLevels: [],
        serviceNames: [],
        filterGroup: { type: FilterLogicalOperator.And, values: [] },
    },
}

export interface LogsViewerConfigProps {
    id: string
}

export const logsViewerConfigLogic = kea<logsViewerConfigLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'config', 'logsViewerConfigLogic']),
    props({ id: 'default' } as LogsViewerConfigProps),
    key((props) => props.id),

    actions({
        setFilters: (filters: LogsViewerFilters) => ({ filters }),
        setFilter: (filter: keyof LogsViewerFilters, value: LogsViewerFilters[keyof LogsViewerFilters]) => ({
            filter,
            value,
        }),
    }),

    reducers({
        filters: [
            DEFAULT_LOGS_VIEWER_CONFIG.filters,
            {
                setFilters: (_, { filters }) => filters,
                setFilter: (state, { filter, value }) => ({
                    ...state,
                    [filter]: value,
                }),
            },
        ],
    }),

    selectors({
        config: [(s) => [s.filters], (filters: LogsViewerFilters): LogsViewerConfig => ({ filters })],
    }),
])
