import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { logsGroupByCreate } from 'products/logs/frontend/generated/api'
import type {
    _LogPropertyFilterApi,
    _LogsGroupByGroupApi,
    _LogsGroupByResponseApi,
    OrderGroupsByEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import type { logsGroupByLogicType } from './logsGroupByLogicType'

export interface LogsGroupByLogicProps {
    id: string
}

const EMPTY_RESPONSE: _LogsGroupByResponseApi = {
    groups: [],
    total_groups: 0,
    total_logs: 0,
    truncated: false,
}

// Keyed by the Viewer's `id`: the logic mounts only while a grouping key is active (the
// Viewer conditionally renders <LogsGroupByResults/>), so loading on mount + reloading on
// the shared filter actions never runs the aggregation while the user is in plain Logs mode.
export const logsGroupByLogic = kea<logsGroupByLogicType>([
    props({ id: 'default' } as LogsGroupByLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'logs', 'frontend', 'components', 'LogsGroupBy', 'logsGroupByLogic', key]),

    connect((props: LogsGroupByLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            logsViewerFiltersLogic({ id: props.id }),
            ['filters', 'utcDateRange', 'queryFilterGroup'],
            logsViewerConfigLogic({ id: props.id }),
            ['groupBy'],
        ],
        actions: [
            logsViewerFiltersLogic({ id: props.id }),
            [
                'setDateRange',
                'zoomDateRange',
                'setSeverityLevels',
                'setServiceNames',
                'setSearchTerm',
                'setFilters',
                'setFilterGroup',
                'setPinnedFilters',
            ],
            logsViewerConfigLogic({ id: props.id }),
            ['setGroupBy'],
        ],
    })),

    actions({
        setOrderGroupsBy: (orderGroupsBy: OrderGroupsByEnumApi) => ({ orderGroupsBy }),
    }),

    loaders(({ values }) => ({
        groupByResponse: [
            EMPTY_RESPONSE,
            {
                loadGroups: async (debounceMs: number = 0, breakpoint) => {
                    await breakpoint(debounceMs)
                    if (!values.groupBy) {
                        return EMPTY_RESPONSE
                    }
                    return await logsGroupByCreate(String(values.currentTeamId), {
                        query: {
                            dateRange: values.utcDateRange,
                            severityLevels: values.filters.severityLevels,
                            serviceNames: values.filters.serviceNames,
                            searchTerm: values.filters.searchTerm || undefined,
                            // Same scoping as Logs/Patterns: `queryFilterGroup` folds in any pinned
                            // filters from an embedded viewer, so a scoped viewer can't aggregate
                            // project-wide logs.
                            filterGroup: values.queryFilterGroup as unknown as _LogPropertyFilterApi[],
                            groupBy: values.groupBy.key,
                            groupBySource: values.groupBy.source,
                            orderGroupsBy: values.orderGroupsBy,
                        },
                    })
                },
            },
        ],
    })),

    reducers({
        orderGroupsBy: [
            'log_count' as OrderGroupsByEnumApi,
            {
                setOrderGroupsBy: (_, { orderGroupsBy }) => orderGroupsBy,
            },
        ],
        // A failed aggregation (e.g. the scan exceeding its byte budget) must surface as an
        // error, not render as "no groups found" — that would misrepresent the data.
        groupByError: [
            null as string | null,
            {
                loadGroups: () => null,
                loadGroupsSuccess: () => null,
                loadGroupsFailure: (_, { error }) => error ?? 'Grouping failed',
            },
        ],
    }),

    selectors({
        // Clear groups when the load fails so LemonTable's emptyState (and the error) shows
        // instead of stale rows — kea-loaders leaves groupByResponse untouched on failure.
        groups: [
            (s) => [s.groupByResponse, s.groupByError],
            (response: _LogsGroupByResponseApi, error: string | null): _LogsGroupByGroupApi[] =>
                error ? [] : response.groups,
        ],
    }),

    listeners(({ actions }) => {
        // Debounced so a multi-filter change or search typing collapses into one request —
        // kea's breakpoint cancels superseded loads before the fetch fires.
        const reload = (): void => actions.loadGroups(300)
        return {
            setDateRange: reload,
            zoomDateRange: reload,
            setSeverityLevels: reload,
            setServiceNames: reload,
            setSearchTerm: reload,
            setFilters: reload,
            setFilterGroup: reload,
            setPinnedFilters: reload,
            // Immediate: switching the grouping key or ranking column is a deliberate click.
            setGroupBy: () => actions.loadGroups(),
            setOrderGroupsBy: () => actions.loadGroups(),
        }
    }),

    afterMount(({ actions }) => {
        actions.loadGroups()
    }),
])
