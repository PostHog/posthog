import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import { LogsSparklineBreakdownBy } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import { LogsViewerConfig, LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import { LogsOrderBy } from 'products/logs/frontend/types'

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

export const DEFAULT_SPARKLINE_BREAKDOWN_BY: LogsSparklineBreakdownBy = 'severity'

export const DEFAULT_ORDER_BY: LogsOrderBy = 'latest'

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
        setSparklineBreakdownBy: (sparklineBreakdownBy: LogsSparklineBreakdownBy) => ({ sparklineBreakdownBy }),
        setOrderBy: (orderBy: LogsOrderBy, source: 'header' | 'toolbar' = 'toolbar') => ({ orderBy, source }),
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
        sparklineBreakdownBy: [
            DEFAULT_SPARKLINE_BREAKDOWN_BY as LogsSparklineBreakdownBy,
            { persist: true },
            {
                setSparklineBreakdownBy: (_, { sparklineBreakdownBy }) => sparklineBreakdownBy,
            },
        ],
        orderBy: [
            DEFAULT_ORDER_BY as LogsOrderBy,
            {
                setOrderBy: (_, { orderBy }) => orderBy,
            },
        ],
    }),

    selectors({
        config: [(s) => [s.filters], (filters: LogsViewerFilters): LogsViewerConfig => ({ filters })],
    }),
])
