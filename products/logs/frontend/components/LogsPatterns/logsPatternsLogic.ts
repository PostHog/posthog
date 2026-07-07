import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import type { LogsQuery } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
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

// The severity filter is an exact match on these six buckets; a pattern whose single sampled
// severity is non-canonical (e.g. "notice") must not be narrowed to a filter that matches nothing.
const CANONICAL_SEVERITIES = ['trace', 'debug', 'info', 'warn', 'error', 'fatal']

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
            logsViewerConfigLogic({ id: props.id }),
            ['setViewMode'],
        ],
    })),

    actions({
        viewMatchingLogs: (pattern: _LogPatternApi) => ({ pattern }),
    }),

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

    listeners(({ actions, values }) => {
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

            // Pivot to the Logs view scoped to this pattern. The predicate lands in the shared
            // filterGroup like any user-added filter — visible and removable in the filter bar,
            // never hidden state. Prefer the validated regex; fall back to plain-text matching
            // on the template's literal content when validation withheld it.
            viewMatchingLogs: ({ pattern }) => {
                const predicate = pattern.match_regex
                    ? {
                          key: 'message',
                          value: pattern.match_regex,
                          operator: PropertyOperator.Regex,
                          type: PropertyFilterType.Log,
                      }
                    : pattern.match_literal
                      ? {
                            key: 'message',
                            value: pattern.match_literal,
                            operator: PropertyOperator.IContains,
                            type: PropertyFilterType.Log,
                        }
                      : null
                if (!predicate) {
                    return
                }
                const group = values.filters.filterGroup
                const inner = group.values[0] as UniversalFiltersGroup | undefined
                const newGroup: UniversalFiltersGroup =
                    inner && Array.isArray(inner.values)
                        ? {
                              ...group,
                              values: [{ ...inner, values: [...inner.values, predicate] }, ...group.values.slice(1)],
                          }
                        : {
                              type: FilterLogicalOperator.And,
                              values: [{ type: FilterLogicalOperator.And, values: [predicate] }],
                          }
                actions.setFilterGroup(newGroup, false)
                // When the sample is unambiguous, scope by service and severity too: service_name
                // is in the table's sort key and severity is indexed, so these prune the scan the
                // body regex alone can't. Both land as visible filter chips the user can remove if
                // the pattern turns out to exist beyond what the sample saw.
                if (pattern.services.length === 1) {
                    actions.setServiceNames(pattern.services)
                }
                const severities = Object.keys(pattern.severity_counts)
                if (severities.length === 1 && CANONICAL_SEVERITIES.includes(severities[0])) {
                    actions.setSeverityLevels([severities[0]] as LogsQuery['severityLevels'])
                }
                actions.setViewMode('logs')
            },
        }
    }),

    afterMount(({ actions }) => {
        actions.loadPatterns()
    }),
])
