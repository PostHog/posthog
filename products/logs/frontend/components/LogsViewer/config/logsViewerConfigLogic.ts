import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import { LogsSparklineBreakdownBy } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import { LogsViewerConfig, LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import type { GroupBySourceEnumApi } from 'products/logs/frontend/generated/api.schemas'
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

export type LogsViewerViewMode = 'logs' | 'patterns' | 'group'
export const DEFAULT_VIEW_MODE: LogsViewerViewMode = 'logs'

export interface LogsViewerGroupBy {
    key: string
    // Where the key lives, in the group-by endpoint's vocabulary: "log" / "resource"
    // attribute maps, or "column" for top-level log fields (severity_level, trace_id, span_id).
    source: GroupBySourceEnumApi
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
        setSparklineBreakdownBy: (sparklineBreakdownBy: LogsSparklineBreakdownBy) => ({ sparklineBreakdownBy }),
        setOrderBy: (orderBy: LogsOrderBy, source: 'header' | 'toolbar' = 'toolbar') => ({ orderBy, source }),
        toggleSparklineCollapsed: true,
        setFacetRailCollapsed: (facetRailCollapsed: boolean) => ({ facetRailCollapsed }),
        setViewMode: (viewMode: LogsViewerViewMode) => ({ viewMode }),
        setGroupBy: (groupBy: LogsViewerGroupBy | null) => ({ groupBy }),
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
        sparklineCollapsed: [
            false,
            { persist: true },
            {
                toggleSparklineCollapsed: (state) => !state,
            },
        ],
        facetRailCollapsed: [
            false,
            { persist: true },
            {
                setFacetRailCollapsed: (_, { facetRailCollapsed }) => facetRailCollapsed,
            },
        ],
        orderBy: [
            DEFAULT_ORDER_BY as LogsOrderBy,
            {
                setOrderBy: (_, { orderBy }) => orderBy,
            },
        ],
        // Not persisted — the Viewer always opens in Logs mode; Patterns is an explicit switch.
        viewMode: [
            DEFAULT_VIEW_MODE as LogsViewerViewMode,
            {
                setViewMode: (_, { viewMode }) => viewMode,
            },
        ],
        // The Group view's configuration: which key to group by (behind the logs-group-by flag).
        // Kept separate from viewMode so the key survives switching lenses within a visit —
        // Logs and back returns to the same grouping. null = no key chosen yet (empty state).
        // Not persisted across visits — grouping is an explicit, per-visit exploration like Patterns.
        groupBy: [
            null as LogsViewerGroupBy | null,
            {
                setGroupBy: (_, { groupBy }) => groupBy,
            },
        ],
    }),

    selectors({
        config: [(s) => [s.filters], (filters: LogsViewerFilters): LogsViewerConfig => ({ filters })],
    }),
])
