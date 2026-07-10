import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

import type { LogsQuery } from '~/queries/schema/schema-general'
import {
    FilterLogicalOperator,
    LogPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { logsPatternsCreate, logsPatternsDiffCreate } from 'products/logs/frontend/generated/api'
import type {
    _LogPatternApi,
    _LogPropertyFilterApi,
    _LogsPatternsDiffResponseApi,
    _LogsPatternsResponseApi,
} from 'products/logs/frontend/generated/api.schemas'

import type { logsPatternsLogicType } from './logsPatternsLogicType'

export interface LogsPatternsLogicProps {
    id: string
}

// 'lastWeek' omits baselineDateRange so the backend defaults to the same window one week
// earlier (absorbs daily/weekly cycles); 'preceding' compares against the window immediately
// before the current one (the post-deploy / incident-onset comparison).
export type PatternsBaselineMode = 'lastWeek' | 'preceding'

// The severity filter is an exact match on these six buckets; a sampled severity outside them
// (e.g. "notice") can't be expressed, so applying the filter would silently exclude those lines.
const CANONICAL_SEVERITIES = ['trace', 'debug', 'info', 'warn', 'error', 'fatal']

// Mirrors the miner's LOGS_PATTERNS_MAX_SERVICES default: a services list this long may have
// been truncated at the cap, so filtering by it could exclude services the pattern also hits.
// severity_counts has no cap, so it never needs this guard.
const SERVICES_LIST_CAP = 4

// Explicit baseline window for 'preceding' mode: the same-length window ending where the
// current one starts. Computed at request time (not memoized) because a relative range like
// "-1h" resolves against "now" — a cached computation would drift away from the current
// window the backend resolves at query time. 'lastWeek' sends no baseline: the backend's
// default is the current window shifted back one week, from its own resolved bounds.
export function precedingDateRange(utcDateRange: { date_from?: string | null; date_to?: string | null }): {
    date_from: string
    date_to: string
} {
    const from = dateStringToDayJs(utcDateRange.date_from ?? null) ?? dayjs().subtract(1, 'hour')
    const to = dateStringToDayJs(utcDateRange.date_to ?? null) ?? dayjs()
    const windowMs = Math.max(to.diff(from), 0)
    return {
        date_from: from.subtract(windowMs, 'millisecond').toISOString(),
        date_to: from.toISOString(),
    }
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
            logsViewerConfigLogic({ id: props.id }),
            ['viewMode'],
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
        setCompareEnabled: (enabled: boolean) => ({ enabled }),
        setBaselineMode: (mode: PatternsBaselineMode) => ({ mode }),
    }),

    loaders(({ values }) => ({
        patternsResponse: [
            EMPTY_RESPONSE,
            {
                loadPatterns: async (debounceMs: number = 0, breakpoint) => {
                    await breakpoint(debounceMs)
                    const response = await logsPatternsCreate(String(values.currentTeamId), {
                        query: values.patternsQueryBody,
                    })
                    // A superseded call must not land its (stale) response after the newer one.
                    breakpoint()
                    return response
                },
            },
        ],
        diffResponse: [
            null as _LogsPatternsDiffResponseApi | null,
            {
                loadDiff: async (debounceMs: number = 0, breakpoint) => {
                    await breakpoint(debounceMs)
                    const response = await logsPatternsDiffCreate(String(values.currentTeamId), {
                        query: values.patternsQueryBody,
                        baselineDateRange:
                            values.baselineMode === 'preceding' ? precedingDateRange(values.utcDateRange) : undefined,
                    })
                    breakpoint()
                    return response
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
                loadDiff: () => null,
                loadDiffSuccess: () => null,
                loadDiffFailure: (_, { error }) => error ?? 'Pattern comparison failed',
            },
        ],
        compareEnabled: [
            false,
            {
                setCompareEnabled: (_, { enabled }) => enabled,
            },
        ],
        baselineMode: [
            'lastWeek' as PatternsBaselineMode,
            {
                setBaselineMode: (_, { mode }) => mode,
            },
        ],
    }),

    selectors({
        // The shared query body for both the mine and the diff — the diff must scope its two
        // windows with exactly the filters a plain mine would use, or compare mode would
        // silently answer a different question than the table next to it.
        patternsQueryBody: [
            (s) => [s.filters, s.utcDateRange, s.queryFilterGroup],
            (filters, utcDateRange, queryFilterGroup) => ({
                dateRange: utcDateRange,
                severityLevels: filters.severityLevels,
                serviceNames: filters.serviceNames,
                searchTerm: filters.searchTerm || undefined,
                // Scope mining to the same filters the Logs/sparkline queries use —
                // `queryFilterGroup` folds in any pinned filters from an embedded viewer
                // (person/trace logs), so a scoped viewer can't mine project-wide patterns.
                filterGroup: queryFilterGroup as unknown as _LogPropertyFilterApi[],
            }),
        ],
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
        // kea's breakpoint cancels superseded loads before the fetch fires. Only mine while
        // Patterns is the active view: the pivot below flips to Logs mode before writing its
        // filter, so its own `setFilterGroup` (and any deferred unmount) can't queue a stray mine.
        const reload = (): void => {
            if (values.viewMode !== 'patterns') {
                return
            }
            if (values.compareEnabled) {
                actions.loadDiff(300)
            } else {
                actions.loadPatterns(300)
            }
        }
        return {
            setDateRange: reload,
            zoomDateRange: reload,
            setSeverityLevels: reload,
            setServiceNames: reload,
            setSearchTerm: reload,
            setFilters: reload,
            setFilterGroup: reload,
            setPinnedFilters: reload,

            // Entering compare mode always diffs fresh; leaving it re-mines because the
            // filters may have changed while the plain response sat unused.
            setCompareEnabled: ({ enabled }) => {
                if (enabled) {
                    actions.loadDiff()
                } else {
                    actions.loadPatterns()
                }
            },
            setBaselineMode: () => {
                if (values.compareEnabled) {
                    actions.loadDiff()
                }
            },

            // Pivot to the Logs view scoped to this pattern. The predicate lands in the shared
            // filterGroup like any user-added filter — visible and removable in the filter bar,
            // never hidden state. Prefer the validated regex; fall back to plain-text matching
            // on the template's literal content when validation withheld it.
            viewMatchingLogs: ({ pattern }) => {
                const predicate: LogPropertyFilter | null = pattern.match_regex
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
                              values: [
                                  { ...inner, values: [...inner.values, predicate] } as UniversalFiltersGroup,
                                  ...group.values.slice(1),
                              ],
                          }
                        : {
                              type: FilterLogicalOperator.And,
                              values: [
                                  { type: FilterLogicalOperator.And, values: [predicate] } as UniversalFiltersGroup,
                              ],
                          }
                // Leave Patterns mode first so the filter writes below don't re-trigger a mine:
                // the `reload` guard sees Logs mode and bails on our own `setFilterGroup`.
                actions.setViewMode('logs')
                actions.setFilterGroup(newGroup, false)
                // Scope by every service and severity the sample saw: service_name is in the
                // table's sort key and severity is indexed, so these prune the scan the body regex
                // alone can't. Both are IN filters, so N values narrow just as validly as one, and
                // both land as visible chips the user can remove if the pattern exists beyond the
                // sample. Skipped only when the filter could silently exclude matching lines: a
                // cap-truncated services list, or a severity outside the canonical buckets.
                if (pattern.services.length > 0 && pattern.services.length < SERVICES_LIST_CAP) {
                    actions.setServiceNames(pattern.services)
                }
                const severities = Object.keys(pattern.severity_counts)
                if (severities.length > 0 && severities.every((s) => CANONICAL_SEVERITIES.includes(s))) {
                    actions.setSeverityLevels(severities as LogsQuery['severityLevels'])
                }
            },
        }
    }),

    afterMount(({ actions }) => {
        actions.loadPatterns()
    }),
])
