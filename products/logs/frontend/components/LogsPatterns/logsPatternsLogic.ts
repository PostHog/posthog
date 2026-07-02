import { afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { logsPatternsCreate } from 'products/logs/frontend/generated/api'
import type {
    _LogPatternApi,
    _LogPropertyFilterApi,
    _LogsPatternsResponseApi,
} from 'products/logs/frontend/generated/api.schemas'

import type { logsPatternsLogicType } from './logsPatternsLogicType'

export interface LogsPatternsLogicProps {
    id: string
}

const EMPTY_RESPONSE: _LogsPatternsResponseApi = {
    patterns: [],
    scanned_count: 0,
    total_count: 0,
    sampled: false,
}

// Keyed by the Viewer's `id`: the logic mounts only while the Patterns mode is active (the
// Viewer conditionally renders <LogsPatterns/>), so loading on mount + reloading on the
// shared filter actions never runs the heavier patterns query while the user is in Logs mode.
export const logsPatternsLogic = kea<logsPatternsLogicType>([
    props({ id: 'default' } as LogsPatternsLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'logs', 'frontend', 'components', 'LogsPatterns', 'logsPatternsLogic', key]),

    connect((props: LogsPatternsLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            logsViewerFiltersLogic({ id: props.id }),
            ['filters', 'utcDateRange', 'queryFilterGroup'],
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
        ],
    })),

    loaders(({ values }) => ({
        patternsResponse: [
            EMPTY_RESPONSE,
            {
                loadPatterns: async (debounceMs: number = 0, breakpoint) => {
                    await breakpoint(debounceMs)
                    return await logsPatternsCreate(String(values.currentTeamId), {
                        query: {
                            dateRange: values.utcDateRange,
                            severityLevels: values.filters.severityLevels,
                            serviceNames: values.filters.serviceNames,
                            searchTerm: values.filters.searchTerm || undefined,
                            // Scope mining to the same filters the Logs/sparkline queries use —
                            // `queryFilterGroup` folds in any pinned filters from an embedded viewer
                            // (person/trace logs), so a scoped viewer can't mine project-wide patterns.
                            filterGroup: values.queryFilterGroup as unknown as _LogPropertyFilterApi[],
                        },
                    })
                },
            },
        ],
    })),

    selectors({
        patterns: [
            (s) => [s.patternsResponse],
            (response: _LogsPatternsResponseApi): _LogPatternApi[] => response.patterns,
        ],
    }),

    listeners(({ actions }) => {
        // Debounced so a multi-filter change or search typing collapses into one request —
        // kea's breakpoint cancels superseded loads before the fetch fires.
        const reload = (): void => actions.loadPatterns(300)
        return {
            setDateRange: reload,
            zoomDateRange: reload,
            setSeverityLevels: reload,
            setServiceNames: reload,
            setSearchTerm: reload,
            setFilters: reload,
            setFilterGroup: reload,
            setPinnedFilters: reload,
        }
    }),

    afterMount(({ actions }) => {
        actions.loadPatterns()
    }),
])
