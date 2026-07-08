import { actions, afterMount, kea, key, path, props, reducers, selectors } from 'kea'

import { LogsSparklineBreakdownBy } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import {
    columnsToCustomColumns,
    DEFAULT_LOGS_COLUMNS,
    LogsColumnConfig,
    migrateAttributeColumns,
} from 'products/logs/frontend/components/LogsViewer/config/columns'
import { LogsViewerConfig, LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import type { GroupBySourceEnumApi } from 'products/logs/frontend/generated/api.schemas'
import { AttributeColumnConfig, LogsOrderBy } from 'products/logs/frontend/types'

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

        // Typed columns (unified column model)
        setColumns: (columns: LogsColumnConfig[]) => ({ columns }),
        addColumn: (column: LogsColumnConfig) => ({ column }),
        removeColumn: (id: string) => ({ id }),
        setColumnWidth: (id: string, width: number) => ({ id, width }),
        moveColumn: (id: string, direction: 'left' | 'right') => ({ id, direction }),
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
        columns: [
            DEFAULT_LOGS_COLUMNS,
            { persist: true },
            {
                setColumns: (_, { columns }) => columns,
                addColumn: (state, { column }) => [...state, column],
                removeColumn: (state, { id }) => state.filter((column) => column.id !== id),
                setColumnWidth: (state, { id, width }) =>
                    state.map((column) => (column.id === id ? { ...column, width } : column)),
                moveColumn: (state, { id, direction }) => {
                    const index = state.findIndex((column) => column.id === id)
                    const targetIndex = direction === 'left' ? index - 1 : index + 1
                    if (index === -1 || targetIndex < 0 || targetIndex >= state.length) {
                        return state
                    }
                    const next = [...state]
                    ;[next[index], next[targetIndex]] = [next[targetIndex], next[index]]
                    return next
                },
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

        // Lowered wire value for LogsQuery.customColumns — undefined until a custom column exists
        customColumns: [
            (s) => [s.columns],
            (columns: LogsColumnConfig[]): string[] | undefined => columnsToCustomColumns(columns),
        ],
    }),

    afterMount(({ actions, props, values }) => {
        // One-time migration of the legacy per-attribute column config, which lived (persisted)
        // on logsViewerLogic before the unified column model. Only runs while `columns` is
        // pristine, and removes the legacy key so a later reset-to-default cannot re-migrate.
        const legacyKey = `products.logs.frontend.components.LogsViewer.logsViewerLogic.${props.id}.attributeColumnsConfig`
        try {
            const raw = window.localStorage.getItem(legacyKey)
            if (raw && values.columns === DEFAULT_LOGS_COLUMNS) {
                const legacy: Record<string, AttributeColumnConfig> = JSON.parse(raw)
                const migrated = migrateAttributeColumns(legacy)
                if (migrated.length > 0) {
                    // Legacy table order was timestamp, attribute columns, message
                    const [timestamp, message] = DEFAULT_LOGS_COLUMNS
                    actions.setColumns([timestamp, ...migrated, message])
                }
                window.localStorage.removeItem(legacyKey)
            }
        } catch {
            // Unreadable legacy state: leave defaults in place
        }
    }),
])
