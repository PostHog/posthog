import { afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
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
    sample_coverage_pct: 100,
    sparkline_buckets: [],
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

    // A failed mine (e.g. the sampling query exceeding its execution budget) must surface as
    // an error, not render as "no patterns found" — that would misrepresent the data.
    reducers({
        patternsError: [
            null as string | null,
            {
                loadPatterns: () => null,
                loadPatternsSuccess: () => null,
                loadPatternsFailure: (_, { error }) => error ?? 'Pattern analysis failed',
            },
        ],
    }),

    selectors({
        patterns: [
            (s) => [s.patternsResponse],
            (response: _LogsPatternsResponseApi): _LogPatternApi[] => response.patterns,
        ],
        // Hover labels for the per-pattern sparklines, aligned with each pattern's `sparkline`
        // values. Buckets under a day apart show time-of-day; wider windows include the date.
        sparklineLabels: [
            (s) => [s.patternsResponse],
            (response: _LogsPatternsResponseApi): string[] => {
                const buckets = response.sparkline_buckets
                if (!buckets.length) {
                    return []
                }
                const first = dayjs(buckets[0].start)
                const last = dayjs(buckets[buckets.length - 1].end)
                const format = last.diff(first, 'hour') >= 24 ? 'MMM D HH:mm' : 'HH:mm'
                return buckets.map((b) => `${dayjs(b.start).format(format)} – ${dayjs(b.end).format(format)}`)
            },
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
