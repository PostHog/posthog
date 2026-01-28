import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { FilterLogicalOperator } from '~/types'

import { logsViewerColumnLogic } from 'products/logs/frontend/components/LogsViewer/columns/logsViewerColumnLogic'
import { Column } from 'products/logs/frontend/components/LogsViewer/columns/types'
import {
    LogsViewerConfig,
    LogsViewerConfigVersion,
    LogsViewerFilters,
} from 'products/logs/frontend/components/LogsViewer/config/types'
import { LogsOrderBy } from 'products/logs/frontend/types'

import type { logsViewerConfigLogicType } from './logsViewerConfigLogicType'

const CONFIG_VERSION: LogsViewerConfigVersion = 1

const DEFAULT_FILTERS: LogsViewerFilters = {
    dateRange: { date_from: '-1h', date_to: null },
    searchTerm: '',
    severityLevels: [],
    serviceNames: [],
    filterGroup: { type: FilterLogicalOperator.And, values: [] },
}

const DEFAULT_ORDER_BY: LogsOrderBy = 'latest'

export interface LogsViewerConfigProps {
    id: string
}

export const logsViewerConfigLogic = kea<logsViewerConfigLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'config', 'logsViewerConfigLogic']),
    props({ id: 'default' } as LogsViewerConfigProps),
    key((props) => props.id),
    connect(({ id }: LogsViewerConfigProps) => ({
        values: [logsViewerColumnLogic({ id }), ['columns']],
    })),

    actions({
        setOrderBy: (orderBy: LogsOrderBy, source: 'header' | 'toolbar' = 'toolbar') => ({ orderBy, source }),
        setFilters: (filters: LogsViewerFilters) => ({ filters }),
        setFilter: (filter: keyof LogsViewerFilters, value: LogsViewerFilters[keyof LogsViewerFilters]) => ({
            filter,
            value,
        }),
    }),

    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (_, { filters }) => filters,
                setFilter: (state, { filter, value }) => ({
                    ...state,
                    [filter]: value,
                }),
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
        config: [
            (s) => [s.filters, s.columns, s.orderBy],
            (filters: LogsViewerFilters, columns: Record<string, Column>, orderBy: LogsOrderBy): LogsViewerConfig => ({
                filters,
                columns,
                orderBy,
                version: CONFIG_VERSION,
            }),
        ],
    }),
])
