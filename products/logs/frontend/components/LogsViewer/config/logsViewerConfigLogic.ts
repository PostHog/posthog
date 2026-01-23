import { actions, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { objectsEqual } from 'lib/utils'

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
    config: LogsViewerConfig
    onFiltersChanged?: (filters: LogsViewerFilters) => void
    onConfigChanged?: (config: LogsViewerConfig) => void
}

export const logsViewerConfigLogic = kea<logsViewerConfigLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'config', 'logsViewerConfigLogic']),
    props({ id: 'default', config: DEFAULT_LOGS_VIEWER_CONFIG } as LogsViewerConfigProps),
    key((props) => props.id),

    actions({
        setFilters: (filters: LogsViewerFilters) => ({ filters }),
        setFilter: (filter: keyof LogsViewerFilters, value: LogsViewerFilters[keyof LogsViewerFilters]) => ({
            filter,
            value,
        }),
    }),

    reducers(({ props }) => ({
        filters: [
            props.config.filters,
            {
                setFilters: (_, { filters }) => filters,
                setFilter: (state, { filter, value }) => ({
                    ...state,
                    [filter]: value,
                }),
            },
        ],
    })),

    selectors({
        config: [(s) => [s.filters], (filters: LogsViewerFilters): LogsViewerConfig => ({ filters })],
    }),

    subscriptions(({ props, values }) => ({
        filters: (filters: LogsViewerFilters, oldFilters: LogsViewerFilters) => {
            if (objectsEqual(filters, oldFilters)) {
                return
            }
            props.onFiltersChanged?.(filters)
            props.onConfigChanged?.(values.config)
        },
    })),

    propsChanged(({ actions, props }, oldProps) => {
        if (!objectsEqual(props.config.filters, oldProps.config.filters)) {
            actions.setFilters(props.config.filters)
        }
    }),
])
