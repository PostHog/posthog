import equal from 'fast-deep-equal'
import { actions, afterMount, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { dayjs } from 'lib/dayjs'

import { DateRange } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import type { tracingFiltersLogicType } from './tracingFiltersLogicType'

export const DEFAULT_DATE_RANGE: DateRange = { date_from: '-1h', date_to: null }
export const DEFAULT_TIMEZONE: string = 'UTC'
export const DEFAULT_SERVICE_NAMES: string[] = []
export const DEFAULT_ORDER_BY = 'timestamp' as const
export const DEFAULT_ORDER_DIRECTION = 'DESC' as const
export const DEFAULT_VIEW_MODE = 'traces' as const

// Column the list is ordered by, and its direction. timestamp+DESC is "latest" (keyset paginated via
// the `after` cursor); duration+DESC/ASC is slowest/fastest (offset paginated). See tracingDataLogic.
export type TracingOrderBy = 'timestamp' | 'duration'
export type TracingOrderDirection = 'ASC' | 'DESC'

// 'traces' groups by trace_id and shows root spans only (one row per trace). 'spans' shows every
// matching span (root and child) flat — backed by the query's flatSpans param. See tracingDataLogic.
export type TracingViewMode = 'traces' | 'spans'

export interface OverlayWindow {
    startMs: number
    endMs: number
}

export interface TracingFilters {
    dateRange: DateRange
    serviceNames: string[]
    filterGroup: UniversalFiltersGroup
    orderBy: TracingOrderBy
    orderDirection: TracingOrderDirection
    viewMode: TracingViewMode
    compareMode: boolean
    /** User-positioned overrides for the two compare windows. Null until the overlay is dragged. */
    currentWindowOverride: OverlayWindow | null
    previousWindowOverride: OverlayWindow | null
}

// The /tracing scene's viewer instance. It is the props default, so uncalled wrappers
// outside a BindLogic still resolve to the scene's instance during the keyed migration.
export const TRACING_SCENE_VIEWER_ID = 'default'

export interface TracingFiltersLogicProps {
    id: string
    // Filters enforced by the embedding surface (e.g. a person profile traces tab pins a
    // distinct-id attribute filter so the tab can't fall back to project-wide traces). Kept
    // entirely separate from the user-editable `filterGroup` — combined with it only at
    // query-build time via `queryFilterGroup`, so the filter chips never see them and can't
    // drop the scope. Mirrors the LogsViewer pattern.
    pinnedFilters?: UniversalFiltersGroup
}

// Combines the user-editable filterGroup with pinned filters (prepended to the inner AND
// group). Used at query-build time so the query stays scoped without putting pinned
// filters into editable state. Same shape as the logs viewer's combineWithPinnedFilters.
export function combineWithPinnedFilters(
    filterGroup: UniversalFiltersGroup,
    pinnedFilters: UniversalFiltersGroup | undefined
): UniversalFiltersGroup {
    if (!pinnedFilters?.values?.length) {
        return filterGroup
    }
    const inner = filterGroup.values[0] as UniversalFiltersGroup | undefined
    const innerValues = inner?.values ?? []
    return {
        ...filterGroup,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: [...pinnedFilters.values, ...innerValues],
            } as UniversalFiltersGroup,
            ...filterGroup.values.slice(1),
        ],
    }
}

export const tracingFiltersLogic = kea<tracingFiltersLogicType>([
    props({ id: TRACING_SCENE_VIEWER_ID } as TracingFiltersLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'tracing', 'frontend', 'tracingFiltersLogic', key]),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setTimezone: (timezone: string) => ({ timezone }),
        setServiceNames: (serviceNames: string[]) => ({ serviceNames }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setSort: (orderBy: TracingOrderBy, orderDirection: TracingOrderDirection) => ({ orderBy, orderDirection }),
        setViewMode: (viewMode: TracingViewMode) => ({ viewMode }),
        setCompareMode: (compareMode: boolean) => ({ compareMode }),
        /**
         * Persist the user-dragged overlay windows. Both must be supplied. Setting these
         * never touches dateRange — the sparkline range is locked once compare mode is on.
         */
        setOverlayWindows: (current: OverlayWindow, previous: OverlayWindow) => ({ current, previous }),
        setFilters: (filters: Partial<TracingFilters>) => ({ filters }),
        // Mirror of the `pinnedFilters` prop into state so consumers can read it via
        // useValues without going through the kea selector input-prop machinery
        // (which doesn't accept optional props).
        setPinnedFilters: (pinnedFilters: UniversalFiltersGroup | undefined) => ({ pinnedFilters }),
    }),

    reducers({
        dateRange: [
            DEFAULT_DATE_RANGE as DateRange,
            {
                setDateRange: (_, { dateRange }) => dateRange,
                setFilters: (state, { filters }) => filters.dateRange ?? state,
            },
        ],
        timezone: [
            DEFAULT_TIMEZONE,
            { persist: true },
            {
                setTimezone: (_, { timezone }) => timezone,
            },
        ],
        serviceNames: [
            DEFAULT_SERVICE_NAMES as string[],
            {
                setServiceNames: (_, { serviceNames }) => serviceNames,
                setFilters: (state, { filters }) => filters.serviceNames ?? state,
            },
        ],
        filterGroup: [
            DEFAULT_UNIVERSAL_GROUP_FILTER as UniversalFiltersGroup,
            {
                setFilterGroup: (_, { filterGroup }) =>
                    filterGroup && filterGroup.values ? filterGroup : DEFAULT_UNIVERSAL_GROUP_FILTER,
                setFilters: (state, { filters }) =>
                    filters.filterGroup && filters.filterGroup.values ? filters.filterGroup : state,
            },
        ],
        orderBy: [
            DEFAULT_ORDER_BY as TracingOrderBy,
            {
                setSort: (_, { orderBy }) => orderBy,
                setFilters: (state, { filters }) => (filters.orderBy as TracingOrderBy) ?? state,
            },
        ],
        orderDirection: [
            DEFAULT_ORDER_DIRECTION as TracingOrderDirection,
            {
                setSort: (_, { orderDirection }) => orderDirection,
                setFilters: (state, { filters }) => (filters.orderDirection as TracingOrderDirection) ?? state,
            },
        ],
        viewMode: [
            DEFAULT_VIEW_MODE as TracingViewMode,
            {
                setViewMode: (_, { viewMode }) => viewMode,
                setFilters: (state, { filters }) => filters.viewMode ?? state,
            },
        ],
        compareMode: [
            false as boolean,
            {
                setCompareMode: (_, { compareMode }) => compareMode,
                setFilters: (state, { filters }) => filters.compareMode ?? state,
            },
        ],
        currentWindowOverride: [
            null as OverlayWindow | null,
            {
                setOverlayWindows: (_, { current }) => current,
                // Any date-range change invalidates user-positioned windows — they were absolute
                // ms positions inside the old sparkline range, meaningless in a new one.
                setDateRange: () => null,
                setCompareMode: () => null,
                setFilters: (state, { filters }) => filters.currentWindowOverride ?? state,
            },
        ],
        previousWindowOverride: [
            null as OverlayWindow | null,
            {
                setOverlayWindows: (_, { previous }) => previous,
                setDateRange: () => null,
                setCompareMode: () => null,
                setFilters: (state, { filters }) => filters.previousWindowOverride ?? state,
            },
        ],
        pinnedFilters: [
            undefined as UniversalFiltersGroup | undefined,
            {
                setPinnedFilters: (_, { pinnedFilters }) => pinnedFilters,
            },
        ],
    }),

    selectors({
        filters: [
            (s) => [
                s.dateRange,
                s.serviceNames,
                s.filterGroup,
                s.orderBy,
                s.orderDirection,
                s.viewMode,
                s.compareMode,
                s.currentWindowOverride,
                s.previousWindowOverride,
            ],
            (
                dateRange,
                serviceNames,
                filterGroup,
                orderBy,
                orderDirection,
                viewMode,
                compareMode,
                currentWindowOverride,
                previousWindowOverride
            ): TracingFilters => ({
                dateRange,
                serviceNames,
                filterGroup,
                orderBy,
                orderDirection,
                viewMode,
                compareMode,
                currentWindowOverride,
                previousWindowOverride,
            }),
        ],
        // The filter group queries must use: the user-editable filterGroup with the
        // embedder's pinned filters merged in. Everything that builds a request reads
        // this, never `filters.filterGroup` directly.
        queryFilterGroup: [
            (s) => [s.filterGroup, s.pinnedFilters],
            (
                filterGroup: UniversalFiltersGroup,
                pinnedFilters: UniversalFiltersGroup | undefined
            ): UniversalFiltersGroup => combineWithPinnedFilters(filterGroup, pinnedFilters),
        ],
        utcDateRange: [
            (s) => [s.dateRange],
            (dateRange: DateRange) => ({
                date_from: dayjs(dateRange.date_from).isValid()
                    ? dayjs(dateRange.date_from).toISOString()
                    : dateRange.date_from,
                date_to: dayjs(dateRange.date_to).isValid()
                    ? dayjs(dateRange.date_to).toISOString()
                    : dateRange.date_to,
            }),
        ],
        sparklineWindowMs: [(s) => [s.dateRange], (dateRange: DateRange): OverlayWindow => resolveWindow(dateRange)],
        currentWindowMs: [
            (s) => [s.sparklineWindowMs, s.currentWindowOverride],
            (sparklineWindowMs: OverlayWindow, override: OverlayWindow | null): OverlayWindow => {
                if (override) {
                    return override
                }
                // Default: right-aligned, 40% of the sparkline duration.
                const duration = sparklineWindowMs.endMs - sparklineWindowMs.startMs
                const windowDuration = duration * 0.4
                return { startMs: sparklineWindowMs.endMs - windowDuration, endMs: sparklineWindowMs.endMs }
            },
        ],
        previousWindowMs: [
            (s) => [s.sparklineWindowMs, s.previousWindowOverride],
            (sparklineWindowMs: OverlayWindow, override: OverlayWindow | null): OverlayWindow => {
                if (override) {
                    return override
                }
                // Default: same 40% width, shifted -50% of sparkline duration from current's
                // right edge — i.e., right edge at end - 50% of duration.
                const duration = sparklineWindowMs.endMs - sparklineWindowMs.startMs
                const windowDuration = duration * 0.4
                const endMs = sparklineWindowMs.endMs - duration * 0.5
                return { startMs: endMs - windowDuration, endMs }
            },
        ],
    }),

    propsChanged(({ actions, props: logicProps }, oldProps) => {
        if (!equal(logicProps.pinnedFilters, oldProps.pinnedFilters)) {
            actions.setPinnedFilters(logicProps.pinnedFilters)
        }
    }),

    afterMount(({ actions, props: logicProps }) => {
        if (logicProps.pinnedFilters) {
            actions.setPinnedFilters(logicProps.pinnedFilters)
        }
    }),
])

function resolveWindow(dateRange: DateRange): { startMs: number; endMs: number } {
    const endMs =
        dateRange.date_to && dayjs(dateRange.date_to).isValid() ? dayjs(dateRange.date_to).valueOf() : Date.now()
    const startMs =
        dateRange.date_from && dayjs(dateRange.date_from).isValid()
            ? dayjs(dateRange.date_from).valueOf()
            : resolveRelativeMs(dateRange.date_from ?? '-1h', endMs)
    return { startMs, endMs }
}

const RELATIVE_RE = /^-(\d+)([smhdM])$/

function resolveRelativeMs(input: string | null | undefined, anchorMs: number): number {
    if (!input) {
        return anchorMs
    }
    const match = RELATIVE_RE.exec(input.trim())
    if (!match) {
        return anchorMs
    }
    const [, nRaw, unit] = match
    const n = Number(nRaw)
    const unitMap: Record<string, dayjs.UnitType> = {
        s: 'second',
        m: 'minute',
        h: 'hour',
        d: 'day',
        M: 'month',
    }
    return dayjs(anchorMs).subtract(n, unitMap[unit]).valueOf()
}
