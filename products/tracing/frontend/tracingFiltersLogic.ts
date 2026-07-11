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

// A comparison is always "A vs B". Named presets compare the full selected date range against
// the same-duration window shifted back; 'custom' exposes the two draggable sparkline windows.
export type TimeComparePreset = 'previous_period' | 'yesterday' | 'last_week' | 'custom'

const DAY_MS = 24 * 60 * 60 * 1000

// 'custom' preset default geometry: side A is the right-aligned 40% of the sparkline range,
// side B the same width with its right edge pulled back 50% of the range.
const CUSTOM_WINDOW_FRACTION = 0.4
const CUSTOM_BASELINE_SHIFT_FRACTION = 0.5

export interface TimeComparePresetDef {
    /** Menu item copy. */
    label: string
    /** How the ComparisonBar's baseline pill describes side B. */
    baselineLabel: string
    /** Baseline shift in ms; null = shift by the current window's own duration. */
    shiftMs: number | null
}

// Single home for per-preset knowledge — menu items, pill copy, window shift, and URL
// validation all derive from this table, so adding a preset means one entry (plus the type).
export const TIME_COMPARE_PRESET_DEFS: Record<TimeComparePreset, TimeComparePresetDef> = {
    previous_period: { label: 'vs previous period', baselineLabel: 'previous period', shiftMs: null },
    yesterday: { label: 'vs yesterday', baselineLabel: 'yesterday', shiftMs: DAY_MS },
    last_week: { label: 'vs same time last week', baselineLabel: 'same time last week', shiftMs: 7 * DAY_MS },
    custom: { label: 'Custom time windows', baselineLabel: 'custom window', shiftMs: null },
}

export const TIME_COMPARE_PRESETS = Object.keys(TIME_COMPARE_PRESET_DEFS) as TimeComparePreset[]

export interface TimeComparison {
    mode: 'time'
    preset: TimeComparePreset
    /** User-positioned overrides for the two compare windows ('custom' preset only). Null until dragged. */
    currentWindowOverride: OverlayWindow | null
    previousWindowOverride: OverlayWindow | null
}

// Future modes ('segment', 'trace') extend this union — see the tracing comparison rework plan.
export type TracingComparison = TimeComparison

export const DEFAULT_CUSTOM_COMPARISON: TimeComparison = {
    mode: 'time',
    preset: 'custom',
    currentWindowOverride: null,
    previousWindowOverride: null,
}

// URL round-trip for the `comparison` search param. Only mode/preset persist — dragged overlay
// windows are ephemeral absolute-ms positions. Future comparison modes extend these two
// functions; the scene logic's URL sync is shape-agnostic.
export function serializeComparison(comparison: TracingComparison | null): string | undefined {
    return comparison ? JSON.stringify({ mode: comparison.mode, preset: comparison.preset }) : undefined
}

export function parseComparison(raw: unknown): TracingComparison | null {
    try {
        const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
        if (parsed?.mode === 'time' && TIME_COMPARE_PRESETS.includes(parsed.preset)) {
            return { ...DEFAULT_CUSTOM_COMPARISON, preset: parsed.preset }
        }
    } catch {
        // Malformed param — treat as no comparison.
    }
    return null
}

export interface TracingFilters {
    dateRange: DateRange
    serviceNames: string[]
    filterGroup: UniversalFiltersGroup
    orderBy: TracingOrderBy
    orderDirection: TracingOrderDirection
    viewMode: TracingViewMode
    comparison: TracingComparison | null
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
        setComparison: (comparison: TracingComparison | null) => ({ comparison }),
        /**
         * Persist the user-dragged overlay windows ('custom' preset only). Both must be supplied.
         * Setting these never touches dateRange — the sparkline range is locked while comparing.
         */
        updateComparisonWindows: (current: OverlayWindow, previous: OverlayWindow) => ({ current, previous }),
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
        comparison: [
            null as TracingComparison | null,
            {
                setComparison: (_, { comparison }) => comparison,
                updateComparisonWindows: (state, { current, previous }) =>
                    state?.mode === 'time'
                        ? { ...state, currentWindowOverride: current, previousWindowOverride: previous }
                        : state,
                // Any date-range change invalidates user-positioned windows — they were absolute
                // ms positions inside the old sparkline range, meaningless in a new one.
                setDateRange: (state) =>
                    state?.mode === 'time' && (state.currentWindowOverride || state.previousWindowOverride)
                        ? { ...state, currentWindowOverride: null, previousWindowOverride: null }
                        : state,
                // `filters.comparison` can legitimately be null (exit comparison), so check presence
                // rather than nullish-coalescing.
                setFilters: (state, { filters }) => (filters.comparison !== undefined ? filters.comparison : state),
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
            (s) => [s.dateRange, s.serviceNames, s.filterGroup, s.orderBy, s.orderDirection, s.viewMode, s.comparison],
            (dateRange, serviceNames, filterGroup, orderBy, orderDirection, viewMode, comparison): TracingFilters => ({
                dateRange,
                serviceNames,
                filterGroup,
                orderBy,
                orderDirection,
                viewMode,
                comparison,
            }),
        ],
        compareActive: [(s) => [s.comparison], (comparison: TracingComparison | null): boolean => comparison !== null],
        // Time-mode narrowing in one place: the window selectors and the fetch layer's time-shift
        // compareFilter must read this, not `compareActive`, so future non-time modes can't
        // silently inherit time-shift semantics.
        timeComparison: [
            (s) => [s.comparison],
            (comparison: TracingComparison | null): TimeComparison | null =>
                comparison?.mode === 'time' ? comparison : null,
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
        // Side A of the comparison (and the window every aggregation covers). Named presets — and
        // no comparison at all, e.g. the Operations tab — use the full selected range; only the
        // 'custom' preset carves out the draggable right-aligned 40% sub-window.
        currentWindowMs: [
            (s) => [s.sparklineWindowMs, s.timeComparison],
            (sparklineWindowMs: OverlayWindow, timeComparison: TimeComparison | null): OverlayWindow => {
                if (timeComparison?.preset !== 'custom') {
                    return sparklineWindowMs
                }
                if (timeComparison.currentWindowOverride) {
                    return timeComparison.currentWindowOverride
                }
                const duration = sparklineWindowMs.endMs - sparklineWindowMs.startMs
                const windowDuration = duration * CUSTOM_WINDOW_FRACTION
                return { startMs: sparklineWindowMs.endMs - windowDuration, endMs: sparklineWindowMs.endMs }
            },
        ],
        // Side B (the baseline): the current window shifted back per the preset. Always equal in
        // duration to side A — the backend infers the compare window's end from that duration.
        previousWindowMs: [
            (s) => [s.sparklineWindowMs, s.currentWindowMs, s.timeComparison],
            (
                sparklineWindowMs: OverlayWindow,
                currentWindowMs: OverlayWindow,
                timeComparison: TimeComparison | null
            ): OverlayWindow => {
                const preset = timeComparison?.preset ?? 'previous_period'
                if (preset === 'custom') {
                    if (timeComparison?.previousWindowOverride) {
                        return timeComparison.previousWindowOverride
                    }
                    const duration = sparklineWindowMs.endMs - sparklineWindowMs.startMs
                    const windowDuration = duration * CUSTOM_WINDOW_FRACTION
                    const endMs = sparklineWindowMs.endMs - duration * CUSTOM_BASELINE_SHIFT_FRACTION
                    return { startMs: endMs - windowDuration, endMs }
                }
                const currentDuration = currentWindowMs.endMs - currentWindowMs.startMs
                const shiftMs = TIME_COMPARE_PRESET_DEFS[preset].shiftMs ?? currentDuration
                return { startMs: currentWindowMs.startMs - shiftMs, endMs: currentWindowMs.endMs - shiftMs }
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
