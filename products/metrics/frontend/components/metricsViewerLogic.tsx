import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/constants'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dayjs } from 'lib/dayjs'
import { escapeRegex } from 'lib/utils/actions'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import {
    NEW_QUERY_STARTED_ERROR_MESSAGE,
    abortResilientLoading,
    isUserInitiatedError,
} from 'lib/utils/kea-logic-builders'
import { objectsEqual } from 'lib/utils/objects'
import { alphabet, truncate } from 'lib/utils/strings'
import { insightsApi } from 'scenes/insights/utils/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    GoalLine,
    MetricsDisplaySettings,
    MetricsDisplayType,
    MetricsQuery,
    MetricsQueryClause,
    MetricsYAxisSettings,
    NodeKind,
} from '~/queries/schema/schema-general'
import { QueryBasedInsightModel } from '~/types'
import { PropertyFilterType, PropertyOperator, UniversalFilterValue, UniversalFiltersGroup } from '~/types'

import {
    metricsAttributesRetrieve,
    metricsCharacterizeCreate,
    metricsQueryCreate,
} from 'products/metrics/frontend/generated/api'
import { OtelMetricTypeEnumApi } from 'products/metrics/frontend/generated/api.schemas'
import type {
    _MetricAnomalyBodyApi,
    _MetricAnomalyReportApi,
    _MetricClauseApi,
    _MetricFilterApi,
    _MetricQueryBodyApi,
    _MetricSeriesApi,
    MetricAnomalyDirectionEnumApi,
} from 'products/metrics/frontend/generated/api.schemas'
import { canCreateMetricsInsight, canViewMetrics } from 'products/metrics/frontend/metricsAccess'

import type { Node } from '../../../../frontend/src/queries/schema/schema-general'
import type { _MetricNameApi } from '../generated/api.schemas'
import { type MetricTopMoverRow, topMoverRows } from '../metricsAnomaly'
import { EMPTY_SERVICE_PATTERN, SERVICE_NAME_KEY } from '../metricsAttributes'
import { correlationServiceNames } from '../metricsLinks'
import { metricNamePickerLogic } from './metricNamePickerLogic'
import type { MetricNameItem } from './metricNamePickerLogic'
import type { MetricsChartSeries } from './metricsSeries'

// A derived type ((typeof METRIC_AGGREGATIONS)[number]) would keep these in sync, but
// kea-typegen inlines derived unions into every consumer's generated block — keep the
// named alias so those blocks stay stable.
export type MetricAggregation = 'sum' | 'avg' | 'count' | 'min' | 'max' | 'p95' | 'rate' | 'increase'
export const METRIC_AGGREGATIONS: MetricAggregation[] = ['sum', 'avg', 'count', 'min', 'max', 'p95', 'rate', 'increase']

/** Narrows an untrusted value (a URL param, a saved link) to an aggregation the backend accepts. */
export const isMetricAggregation = (value: unknown): value is MetricAggregation =>
    typeof value === 'string' && METRIC_AGGREGATIONS.includes(value as MetricAggregation)

export { EMPTY_SERVICE_PATTERN, SERVICE_NAME_KEY }

export type MetricsViewerSeries = _MetricSeriesApi

/** One query line of the viewer — the state behind one clause row. */
export interface MetricsViewerClause {
    /** Alias a formula refers to; unique within the query (a, b, c…). */
    name: string
    metricName: string
    selectedMetricType: OtelMetricTypeEnumApi | null
    aggregation: MetricAggregation
    aggregationExplicitlySet: boolean
    filterGroup: UniversalFiltersGroup
    groupByKeys: string[]
}

export interface MetricsViewerQueryState {
    clauses: MetricsViewerClause[]
    /** Which clause the samples panel, anomaly badge, and picker scoping follow. */
    activeClauseIndex: number
    /** Arithmetic over clause aliases (e.g. "a / b"); empty string means off. */
    formula: string
}

/** One clause's share of the picker's late type/aggregation backfill. */
export interface MetricsViewerClauseBackfill {
    index: number
    metricType?: OtelMetricTypeEnumApi
    aggregation?: MetricAggregation
}

// Request-body slices the viewer assembles; the window fields are added at fetch time.
export type MetricsQueryRequestBody = Pick<_MetricQueryBodyApi, 'clauses' | 'formula'>
export type MetricsAnomalyRequestBody = Pick<_MetricAnomalyBodyApi, 'metricName' | 'aggregation' | 'filters'>

// Mirrors the backend's MAX_CLAUSES_PER_QUERY.
export const MAX_CLAUSES = 10
// More letters than MAX_CLAUSES, so the cap is the only thing that limits adding
// a series — a shorter alias supply would make "Add series" silently no-op.
const CLAUSE_ALIASES = alphabet.map((letter) => letter.toLowerCase())

export const createViewerClause = (name: string): MetricsViewerClause => ({
    name,
    metricName: '',
    selectedMetricType: null,
    aggregation: DEFAULT_AGGREGATION,
    aggregationExplicitlySet: false,
    filterGroup: DEFAULT_UNIVERSAL_GROUP_FILTER,
    groupByKeys: [],
})

const nextClauseAlias = (clauses: MetricsViewerClause[]): string | null => {
    if (clauses.length >= MAX_CLAUSES) {
        return null
    }
    const used = new Set(clauses.map((clause) => clause.name))
    for (const letter of CLAUSE_ALIASES) {
        if (!used.has(letter)) {
            return letter
        }
    }
    return null
}

// Clause aliases are lowercase and the backend formula parser is case-sensitive,
// so input is lowercased rather than rejected. Underscores stay — the alias grammar
// (and the backend tokenizer) allows them. The backend caps formulas at 512 chars.
export const sanitizeFormulaInput = (value: string): string =>
    value
        .toLowerCase()
        .replace(/[^a-z0-9_ +\-*/().]/g, '')
        .slice(0, 512)

// Display shape for the "vs baseline" anomaly badge (null = no anomaly / flat metric).
export interface MetricsAnomalyBadge {
    direction: MetricAnomalyDirectionEnumApi
    percent: number
    baselineMean: number
    anomalyMean: number
    onsetTime: string | null
}

export const DEFAULT_AGGREGATION: MetricAggregation = 'sum'

// Aggregation applied automatically when a metric of this type is selected.
// Cumulative counters (OTel type 'sum') summed raw give meaningless ever-growing
// totals — 'increase' is the honest default and is temporality-aware server-side
// (delta samples are summed as-is), so it's correct for delta producers too.
export const RECOMMENDED_AGGREGATION_BY_TYPE: Record<string, MetricAggregation> = {
    gauge: 'avg',
    sum: 'increase',
    counter: 'increase',
    histogram: 'p95',
    summary: 'p95',
    exponential_histogram: 'p95',
}
export const DEFAULT_DATE_FROM = '-1h'
// Kept off the persisted node: a saved query with no `display` renders as a line chart anyway.
export const DEFAULT_DISPLAY_TYPE: MetricsDisplayType = 'line'
// The anomaly badge characterizes the most recent slice of the selected window against the rest.
const ANOMALY_WINDOW_FRACTION = 0.2
export const LIVE_REFRESH_MS = 15_000
const LIVE_REFRESH_KEY = 'metricsLiveRefresh'

// The metrics backend speaks Prometheus-style label matchers, not the full PropertyOperator set.
export const METRIC_FILTER_OPERATOR_ALLOWLIST: PropertyOperator[] = [
    PropertyOperator.Exact,
    PropertyOperator.IsNot,
    PropertyOperator.Regex,
    PropertyOperator.NotRegex,
]

const OPERATOR_TO_FILTER_OP: Partial<Record<PropertyOperator, _MetricFilterApi['op']>> = {
    [PropertyOperator.Exact]: 'eq',
    [PropertyOperator.IsNot]: 'neq',
    [PropertyOperator.Regex]: 'regex',
    [PropertyOperator.NotRegex]: 'not_regex',
}

const toValueStrings = (value: unknown): string[] => {
    const raw = Array.isArray(value) ? value : value === null || value === undefined ? [] : [value]
    return raw.map((item) => String(item)).filter((item) => item.length > 0)
}

// Convert one filter-bar chip into the backend's `{key, op, value}` matcher. Filters run with
// scope 'auto' (resource attributes first, datapoint attributes as fallback), so scope is omitted.
// Returns null for chips still being edited (no key/value) or unsupported operators.
const propertyFilterToMetricFilter = (filter: UniversalFilterValue): _MetricFilterApi | null => {
    const key = 'key' in filter && filter.key ? String(filter.key) : ''
    const operator = 'operator' in filter && filter.operator ? filter.operator : PropertyOperator.Exact
    // A non-PropertyOperator value (e.g. an ActionFilter's fields) simply isn't in the map -> null.
    const op = OPERATOR_TO_FILTER_OP[operator as PropertyOperator]
    if (!key || !op) {
        return null
    }
    const values = toValueStrings('value' in filter ? filter.value : null)
    if (values.length === 0) {
        return null
    }
    if (values.length === 1) {
        return { key, op, value: values[0] }
    }
    // Multi-value chips become Prometheus-style alternations: eq/neq turn into an anchored
    // (not-)regex over the escaped literals; regex operators just OR the patterns together.
    if (op === 'eq' || op === 'neq') {
        return {
            key,
            op: op === 'eq' ? 'regex' : 'not_regex',
            value: `^(?:${values.map(escapeRegex).join('|')})$`,
        }
    }
    return { key, op, value: values.map((pattern) => `(?:${pattern})`).join('|') }
}

const flattenFilterValues = (group: UniversalFiltersGroup): UniversalFilterValue[] =>
    group.values.flatMap((value) => (isUniversalGroupFilterLike(value) ? flattenFilterValues(value) : [value]))

/** A clause's filter bar as backend matchers, skipping chips still being edited. */
export const metricFiltersForGroup = (group: UniversalFiltersGroup): _MetricFilterApi[] =>
    flattenFilterValues(group)
        .map(propertyFilterToMetricFilter)
        .filter((f): f is _MetricFilterApi => f !== null)

/** The services a chip pins the query to, or `[]` when it isn't a membership test. */
const serviceChipValues = (chip: UniversalFilterValue): string[] => {
    const operator = 'operator' in chip ? chip.operator : undefined
    const values = toValueStrings('value' in chip ? chip.value : null)
    if (operator === PropertyOperator.Exact) {
        return values
    }
    // `toValueStrings` drops the empty string, so the "unknown service" chip only
    // survives the trip as this regex; anything else narrows in ways an IN cannot.
    if (operator === PropertyOperator.Regex && values.length === 1 && values[0] === EMPTY_SERVICE_PATTERN) {
        return ['']
    }
    return []
}

export const resolveDate = (value: string | null | undefined): string | null => {
    if (!value) {
        return null
    }
    const dj = dateStringToDayJs(value) ?? dayjs(value)
    return dj.isValid() ? dj.toISOString() : null
}

// The picker reports raw ingest strings; only enum members may reach the API.
export const toKnownMetricType = (metricType: string | undefined): OtelMetricTypeEnumApi | null => {
    const known = Object.values(OtelMetricTypeEnumApi) as string[]
    return metricType && known.includes(metricType) ? (metricType as OtelMetricTypeEnumApi) : null
}

/** The REST viewer's 'p95' shorthand maps to the schema node's quantile aggregation. */
export const nodeAggregationFields = (
    aggregation: MetricAggregation
): Pick<MetricsQueryClause, 'aggregation' | 'quantile'> =>
    aggregation === 'p95' ? { aggregation: 'quantile', quantile: 0.95 } : { aggregation }

/** Inverse of `nodeAggregationFields`, for reading a saved node back in viewer vocabulary. */
export const viewerAggregationFromNode = (aggregation: MetricsQueryClause['aggregation'] | undefined): string | null =>
    aggregation === 'quantile' ? 'p95' : (aggregation ?? null)

const clauseToApiClause = (clause: MetricsViewerClause): _MetricClauseApi => {
    const filters = metricFiltersForGroup(clause.filterGroup)
    return {
        name: clause.name,
        metricName: clause.metricName.trim(),
        aggregation: clause.aggregation,
        // Pins the OTel type so a name that exists as several types (e.g. a counter
        // and a gauge) charts only the picked one instead of blending them.
        ...(clause.selectedMetricType ? { metricType: clause.selectedMetricType } : {}),
        ...(filters.length ? { filters } : {}),
        ...(clause.groupByKeys.length ? { groupBy: clause.groupByKeys.map((key) => ({ key })) } : {}),
    }
}

// Derived from the API clause so a new clause field cannot reach one payload and
// miss the other — the two shapes differ only in the aggregation vocabulary.
const clauseToNodeClause = (clause: MetricsViewerClause): MetricsQueryClause =>
    ({
        ...clauseToApiClause(clause),
        ...nodeAggregationFields(clause.aggregation),
    }) as MetricsQueryClause

const insightNameForViewerQuery = (clauses: MetricsViewerClause[], formula: string): string => {
    const names = clauses.map((clause) => clause.metricName.trim())
    let name: string
    if (formula) {
        name = `${formula} (${names.join(', ')})`
    } else if (clauses.length > 1) {
        name = `${names.join(', ')} (${clauses.length} series)`
    } else {
        name = `${names[0]} (${clauses[0].aggregation})`
    }
    return truncate(name, 120)
}

const DEFAULT_QUERY_STATE: MetricsViewerQueryState = {
    clauses: [createViewerClause('a')],
    activeClauseIndex: 0,
    formula: '',
}

const withClauseAt = (
    state: MetricsViewerQueryState,
    index: number,
    update: (clause: MetricsViewerClause) => MetricsViewerClause
): MetricsViewerQueryState =>
    state.clauses[index]
        ? { ...state, clauses: state.clauses.map((clause, i) => (i === index ? update(clause) : clause)) }
        : state

const withActiveClause = (
    state: MetricsViewerQueryState,
    update: (clause: MetricsViewerClause) => MetricsViewerClause
): MetricsViewerQueryState => withClauseAt(state, state.activeClauseIndex, update)

// Aborts a still-running fetch superseded by a new one. An AbortError-named DOMException
// (not a bare string) is what api.ts and the global loader onFailure recognize as a
// cancellation, so the superseded fetch is swallowed rather than logged/captured as an error.
const abortPrevious = (controller: AbortController | null): void => {
    controller?.abort(new DOMException(NEW_QUERY_STARTED_ERROR_MESSAGE, 'AbortError'))
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface metricsViewerLogicValues {
    items: MetricNameItem[] // metricNamePickerLogic
    pickerServices: string[] // metricNamePickerLogic
    currentTeamId: number | null // teamLogic
    activeClause: MetricsViewerClause
    activeClauseIndex: number
    aggregation: MetricAggregation
    anomalyAbortController: AbortController | null
    anomalyBadge: MetricsAnomalyBadge | null
    anomalyFingerprint: string
    anomalyQuery: MetricsAnomalyRequestBody | null
    anomalyReport: _MetricAnomalyReportApi | null
    anomalyReportLoading: boolean
    anomalyTopMovers: MetricTopMoverRow[]
    attributeEndpointFilters: Record<string, string>
    attributeKeyOptions: {
        key: string
        label: string
    }[]
    attributeKeyOptionsLoading: boolean
    chartSeries: MetricsChartSeries[]
    correlationServices: string[]
    dateFrom: string | null
    dateTo: string | null
    displayType: MetricsDisplayType
    filterGroup: UniversalFiltersGroup
    formula: string
    goalLines: GoalLine[]
    groupByKeys: string[]
    groupBySearch: string
    hasMetricName: boolean
    hasResults: boolean
    isAddToDashboardModalOpen: boolean
    lastSavedQueryNode: MetricsQuery | null
    liveRefresh: boolean
    metricName: string
    metricsDisplay: MetricsDisplaySettings | undefined
    metricsQueryNode: MetricsQuery | null
    namedClauses: MetricsViewerClause[]
    pendingAddToDashboard: boolean
    queryAbortController: AbortController | null
    queryError: string | null
    queryFilters: _MetricFilterApi[]
    queryFingerprint: string
    queryLoading: boolean
    queryPayload: MetricsQueryRequestBody | null
    queryResults: MetricsViewerSeries[]
    queryResultsLoading: boolean
    queryState: MetricsViewerQueryState
    savedInsight: QueryBasedInsightModel | null
    savedInsightLoading: boolean
    selectedMetricType: OtelMetricTypeEnumApi | null
    selectedServices: string[]
    viewerClauses: MetricsViewerClause[]
    yAxisSettings: MetricsYAxisSettings
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface metricsViewerLogicActions {
    loadItemsSuccess: (
        items: _MetricNameApi[],
        payload?:
            | {
                  debounce: boolean
              }
            | undefined
    ) => {
        items: _MetricNameApi[]
        payload?: {
            debounce: boolean
        }
    } // metricNamePickerLogic
    setServices: (services: string[]) => {
        services: string[]
    } // metricNamePickerLogic
    addAttributeFilter: (
        key: string,
        value: string
    ) => {
        key: string
        value: string
    }
    addClause: () => {
        value: true
    }
    addGoalLine: () => {
        value: true
    }
    addToDashboard: () => {
        value: true
    }
    backfillClauses: (updates: MetricsViewerClauseBackfill[]) => {
        updates: MetricsViewerClauseBackfill[]
    }
    cancelInProgressAnomaly: (controller: AbortController | null) => {
        controller: AbortController | null
    }
    cancelInProgressQuery: (controller: AbortController | null) => {
        controller: AbortController | null
    }
    clearAnomaly: () => any
    clearAnomalyFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    clearAnomalySuccess: (
        anomalyReport: null,
        payload?: any
    ) => {
        anomalyReport: null
        payload?: any
    }
    closeAddToDashboardModal: () => {
        value: true
    }
    duplicateClause: (index: number) => {
        index: number
    }
    fetchAnomaly: (_: any) => any
    fetchAnomalyFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    fetchAnomalySuccess: (
        anomalyReport: _MetricAnomalyReportApi | null,
        payload?: any
    ) => {
        anomalyReport: _MetricAnomalyReportApi | null
        payload?: any
    }
    fetchQueryResults: (_: any) => any
    fetchQueryResultsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    fetchQueryResultsSuccess: (
        queryResults: _MetricSeriesApi[],
        payload?: any
    ) => {
        queryResults: _MetricSeriesApi[]
        payload?: any
    }
    loadAttributeKeyOptions: (_: any) => any
    loadAttributeKeyOptionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAttributeKeyOptionsSuccess: (
        attributeKeyOptions: {
            key: string
            label: string
        }[],
        payload?: any
    ) => {
        attributeKeyOptions: {
            key: string
            label: string
        }[]
        payload?: any
    }
    openAddToDashboardModal: () => {
        value: true
    }
    removeClause: (index: number) => {
        index: number
    }
    removeGoalLine: (index: number) => {
        index: number
    }
    saveAsInsight: () => any
    saveAsInsightFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    saveAsInsightSuccess: (
        savedInsight: QueryBasedInsightModel<Node<Record<string, any>>> | null,
        payload?: any
    ) => {
        savedInsight: QueryBasedInsightModel<Node<Record<string, any>>> | null
        payload?: any
    }
    setActiveClauseIndex: (index: number) => {
        index: number
    }
    setAggregation: (aggregation: MetricAggregation) => {
        aggregation: MetricAggregation
    }
    setAnomalyAbortController: (controller: AbortController | null) => {
        controller: AbortController | null
    }
    setClauses: (
        clauses: MetricsViewerClause[],
        formula: string
    ) => {
        clauses: MetricsViewerClause[]
        formula: string
    }
    setDateFrom: (dateFrom: string | null) => {
        dateFrom: string | null
    }
    setDateTo: (dateTo: string | null) => {
        dateTo: string | null
    }
    setDisplayType: (displayType: MetricsDisplayType) => {
        displayType: MetricsDisplayType
    }
    setFilterGroup: (filterGroup: UniversalFiltersGroup) => {
        filterGroup: UniversalFiltersGroup
    }
    setFormula: (formula: string) => {
        formula: string
    }
    setGroupByKeys: (groupByKeys: string[]) => {
        groupByKeys: string[]
    }
    setGroupBySearch: (groupBySearch: string) => {
        groupBySearch: string
    }
    setLastSavedQueryNode: (query: MetricsQuery) => {
        query: MetricsQuery
    }
    setLiveRefresh: (liveRefresh: boolean) => {
        liveRefresh: boolean
    }
    setMetricName: (metricName: string) => {
        metricName: string
    }
    setQueryAbortController: (controller: AbortController | null) => {
        controller: AbortController | null
    }
    setRecommendedAggregation: (aggregation: MetricAggregation) => {
        aggregation: MetricAggregation
    }
    setSelectedMetricType: (metricType: OtelMetricTypeEnumApi | null) => {
        metricType: OtelMetricTypeEnumApi | null
    }
    setYAxisSetting: (
        key: keyof MetricsYAxisSettings,
        value: boolean | number | string | undefined
    ) => {
        key: keyof MetricsYAxisSettings
        value: boolean | number | string | undefined
    }
    updateGoalLine: (
        index: number,
        key: keyof GoalLine,
        value: boolean | number | string
    ) => {
        index: number
        key: keyof GoalLine
        value: boolean | number | string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface metricsViewerLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        viewerClauses: (queryState: MetricsViewerQueryState) => MetricsViewerClause[]
        activeClauseIndex: (queryState: MetricsViewerQueryState) => number
        formula: (queryState: MetricsViewerQueryState) => string
        activeClause: (viewerClauses: MetricsViewerClause[], activeClauseIndex: number) => MetricsViewerClause
        metricName: (activeClause: MetricsViewerClause) => string
        selectedMetricType: (activeClause: MetricsViewerClause) => OtelMetricTypeEnumApi | null
        aggregation: (activeClause: MetricsViewerClause) => MetricAggregation
        groupByKeys: (activeClause: MetricsViewerClause) => string[]
        filterGroup: (activeClause: MetricsViewerClause) => UniversalFiltersGroup
        namedClauses: (viewerClauses: MetricsViewerClause[]) => MetricsViewerClause[]
        hasMetricName: (namedClauses: MetricsViewerClause[]) => boolean
        queryPayload: (namedClauses: MetricsViewerClause[], formula: string) => MetricsQueryRequestBody | null
        queryFingerprint: (queryPayload: MetricsQueryRequestBody | null) => string
        anomalyQuery: (namedClauses: MetricsViewerClause[], formula: string) => MetricsAnomalyRequestBody | null
        anomalyFingerprint: (anomalyQuery: MetricsAnomalyRequestBody | null) => string
        metricsDisplay: (
            displayType: MetricsDisplayType,
            goalLines: GoalLine[],
            yAxisSettings: MetricsYAxisSettings
        ) => MetricsDisplaySettings | undefined
        metricsQueryNode: (
            namedClauses: MetricsViewerClause[],
            formula: string,
            dateFrom: string | null,
            dateTo: string | null,
            metricsDisplay: MetricsDisplaySettings | undefined
        ) => MetricsQuery | null
        queryFilters: (activeClause: MetricsViewerClause) => _MetricFilterApi[]
        selectedServices: (activeClause: MetricsViewerClause) => string[]
        correlationServices: (selectedServices: string[], queryResults: _MetricSeriesApi[]) => string[]
        attributeEndpointFilters: (dateFrom: string | null, dateTo: string | null) => Record<string, string>
        chartSeries: (queryResults: _MetricSeriesApi[]) => MetricsChartSeries[]
        hasResults: (queryResults: _MetricSeriesApi[]) => boolean
        anomalyTopMovers: (anomalyReport: _MetricAnomalyReportApi | null) => MetricTopMoverRow[]
        anomalyBadge: (anomalyReport: _MetricAnomalyReportApi | null) => MetricsAnomalyBadge | null
    }
}

export type metricsViewerLogicType = MakeLogicType<
    metricsViewerLogicValues,
    metricsViewerLogicActions,
    Record<string, any>,
    metricsViewerLogicMeta
>

export const metricsViewerLogic = kea<metricsViewerLogicType>([
    path(['products', 'metrics', 'frontend', 'components', 'metricsViewerLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], metricNamePickerLogic, ['items', 'services as pickerServices']],
        actions: [metricNamePickerLogic, ['loadItemsSuccess', 'setServices']],
    })),
    actions({
        // The single-clause setters target the active clause, so everything that
        // followed the viewer's one metric (URL sync, samples, usage tracking)
        // keeps working unchanged with several clauses on screen.
        setMetricName: (metricName: string) => ({ metricName }),
        setSelectedMetricType: (metricType: OtelMetricTypeEnumApi | null) => ({ metricType }),
        setAggregation: (aggregation: MetricAggregation) => ({ aggregation }),
        // Auto-applied on metric switch — a separate action so usage tracking can
        // tell it apart from the user picking an aggregation themselves.
        setRecommendedAggregation: (aggregation: MetricAggregation) => ({ aggregation }),
        setGroupByKeys: (groupByKeys: string[]) => ({ groupByKeys }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        addClause: true,
        removeClause: (index: number) => ({ index }),
        duplicateClause: (index: number) => ({ index }),
        setActiveClauseIndex: (index: number) => ({ index }),
        setFormula: (formula: string) => ({ formula }),
        // Bulk replace, used by the scene's URL restore.
        setClauses: (clauses: MetricsViewerClause[], formula: string) => ({ clauses, formula }),
        // The picker's late type/aggregation backfill, applied to every clause in one
        // pass so a 10-clause deep link costs one reducer run and one URL write.
        backfillClauses: (updates: MetricsViewerClauseBackfill[]) => ({ updates }),
        setDateFrom: (dateFrom: string | null) => ({ dateFrom }),
        setDateTo: (dateTo: string | null) => ({ dateTo }),
        setLiveRefresh: (liveRefresh: boolean) => ({ liveRefresh }),
        setGroupBySearch: (groupBySearch: string) => ({ groupBySearch }),
        // Narrows the chart to one label value, from the anomaly panel's ranked movers.
        addAttributeFilter: (key: string, value: string) => ({ key, value }),
        // Saves the current query as an insight (reusing the last save while the
        // query is unchanged) and opens the dashboard picker for it.
        addToDashboard: true,
        openAddToDashboardModal: true,
        closeAddToDashboardModal: true,
        setLastSavedQueryNode: (query: MetricsQuery) => ({ query }),
        // AbortController plumbing mirrors logsViewerDataLogic: a `cancelInProgress`
        // action aborts the previous controller before storing the new one.
        setQueryAbortController: (controller: AbortController | null) => ({ controller }),
        cancelInProgressQuery: (controller: AbortController | null) => ({ controller }),
        setAnomalyAbortController: (controller: AbortController | null) => ({ controller }),
        cancelInProgressAnomaly: (controller: AbortController | null) => ({ controller }),
        // Chart presentation. These ride along on the saved query node but never reach the query
        // engine, so changing one re-renders without refetching.
        setDisplayType: (displayType: MetricsDisplayType) => ({ displayType }),
        addGoalLine: true,
        updateGoalLine: (index: number, key: keyof GoalLine, value: string | number | boolean) => ({
            index,
            key,
            value,
        }),
        removeGoalLine: (index: number) => ({ index }),
        setYAxisSetting: (key: keyof MetricsYAxisSettings, value: number | string | boolean | undefined) => ({
            key,
            value,
        }),
    }),
    reducers({
        // The clause list, active index, and formula live in one reducer so the
        // active-clause setters can resolve their target synchronously — URL sync
        // and connected listeners read the updated value in the same dispatch.
        queryState: [
            DEFAULT_QUERY_STATE as MetricsViewerQueryState,
            {
                setMetricName: (state, { metricName }) =>
                    // A metric switch drops the previous deliberate aggregation pick,
                    // matching what picking a metric always did.
                    withActiveClause(state, (clause) => ({ ...clause, metricName, aggregationExplicitlySet: false })),
                // The picked metric's type, latched at pick time (and backfilled if the
                // picker list arrives later). Not derived from the picker's `items` —
                // those are live search results, so typing a new search would wipe a
                // derived value and queries/saves would silently go untyped.
                setSelectedMetricType: (state, { metricType }) =>
                    withActiveClause(state, (clause) => ({ ...clause, selectedMetricType: metricType })),
                setAggregation: (state, { aggregation }) =>
                    withActiveClause(state, (clause) => ({ ...clause, aggregation, aggregationExplicitlySet: true })),
                setRecommendedAggregation: (state, { aggregation }) =>
                    withActiveClause(state, (clause) => ({ ...clause, aggregation, aggregationExplicitlySet: false })),
                // Attribute keys to split the clause into one series each (e.g. ['service.name', 'env']).
                setGroupByKeys: (state, { groupByKeys }) =>
                    withActiveClause(state, (clause) => ({ ...clause, groupByKeys })),
                // The clause's UniversalFilters group; converted into backend matchers by `metricFiltersForGroup`.
                setFilterGroup: (state, { filterGroup }) =>
                    withActiveClause(state, (clause) => ({ ...clause, filterGroup })),
                backfillClauses: (state, { updates }) => ({
                    ...state,
                    clauses: state.clauses.map((clause, index) => {
                        const update = updates.find((u) => u.index === index)
                        if (!update) {
                            return clause
                        }
                        return {
                            ...clause,
                            // A backfill never overrides a latched type or a deliberate pick.
                            ...(update.metricType && clause.selectedMetricType === null
                                ? { selectedMetricType: update.metricType }
                                : {}),
                            ...(update.aggregation && !clause.aggregationExplicitlySet
                                ? { aggregation: update.aggregation }
                                : {}),
                        }
                    }),
                }),
                addClause: (state) => {
                    const name = nextClauseAlias(state.clauses)
                    if (!name) {
                        return state
                    }
                    // The new clause becomes active so the picker and samples follow it.
                    return {
                        ...state,
                        clauses: [...state.clauses, createViewerClause(name)],
                        activeClauseIndex: state.clauses.length,
                    }
                },
                duplicateClause: (state, { index }) => {
                    const source = state.clauses[index]
                    const name = nextClauseAlias(state.clauses)
                    if (!source || !name) {
                        return state
                    }
                    const clauses = [...state.clauses]
                    clauses.splice(index + 1, 0, { ...source, name })
                    return { ...state, clauses, activeClauseIndex: index + 1 }
                },
                removeClause: (state, { index }) => {
                    const removed = state.clauses[index]
                    if (state.clauses.length <= 1 || !removed) {
                        return state
                    }
                    const clauses = state.clauses.filter((_, i) => i !== index)
                    const active =
                        state.activeClauseIndex > index ? state.activeClauseIndex - 1 : state.activeClauseIndex
                    // A formula referencing the removed alias can only error; clearing it
                    // keeps the remaining series charted instead of an error banner.
                    // Aliases are word characters, so \b is an exact token boundary.
                    const formula = new RegExp(`\\b${removed.name}\\b`).test(state.formula) ? '' : state.formula
                    return {
                        clauses,
                        activeClauseIndex: Math.max(0, Math.min(active, clauses.length - 1)),
                        formula,
                    }
                },
                setActiveClauseIndex: (state, { index }) =>
                    state.clauses[index] ? { ...state, activeClauseIndex: index } : state,
                setFormula: (state, { formula }) => ({ ...state, formula: sanitizeFormulaInput(formula) }),
                setClauses: (state, { clauses, formula }) =>
                    clauses.length
                        ? {
                              clauses: clauses.slice(0, MAX_CLAUSES),
                              activeClauseIndex: 0,
                              formula: sanitizeFormulaInput(formula),
                          }
                        : state,
            },
        ],
        dateFrom: [DEFAULT_DATE_FROM as string | null, { setDateFrom: (_, { dateFrom }) => dateFrom }],
        dateTo: [null as string | null, { setDateTo: (_, { dateTo }) => dateTo }],
        liveRefresh: [false, { setLiveRefresh: (_, { liveRefresh }) => liveRefresh }],
        // Free-text search backing the group-by attribute-key autocomplete.
        groupBySearch: ['' as string, { setGroupBySearch: (_, { groupBySearch }) => groupBySearch }],
        queryAbortController: [
            null as AbortController | null,
            { setQueryAbortController: (_, { controller }) => controller },
        ],
        anomalyAbortController: [
            null as AbortController | null,
            { setAnomalyAbortController: (_, { controller }) => controller },
        ],
        displayType: [
            DEFAULT_DISPLAY_TYPE as MetricsDisplayType,
            { setDisplayType: (_, { displayType }) => displayType },
        ],
        goalLines: [
            [] as GoalLine[],
            {
                addGoalLine: (state) => [...state, { label: '', value: 0 }],
                updateGoalLine: (state, { index, key, value }) =>
                    state.map((line, i) => (i === index ? { ...line, [key]: value } : line)),
                removeGoalLine: (state, { index }) => state.filter((_, i) => i !== index),
            },
        ],
        yAxisSettings: [
            {} as MetricsYAxisSettings,
            {
                // An undefined value clears the setting rather than persisting an explicit
                // undefined, so an emptied number input goes back to automatic.
                setYAxisSetting: (state, { key, value }) => {
                    const next = { ...state }
                    if (value === undefined) {
                        delete next[key]
                    } else {
                        Object.assign(next, { [key]: value })
                    }
                    return next
                },
            },
        ],
        isAddToDashboardModalOpen: [
            false,
            {
                openAddToDashboardModal: () => true,
                closeAddToDashboardModal: () => false,
            },
        ],
        // The query node exactly as the last successful save sent it. The reuse
        // check compares against this, not the server-returned insight.query —
        // the API may normalize the stored node (injected defaults, version
        // stamps), and a comparison against that would never match and would
        // save a duplicate insight on every click.
        lastSavedQueryNode: [null as MetricsQuery | null, { setLastSavedQueryNode: (_, { query }) => query }],
        // Armed while an addToDashboard-initiated save is in flight, so the success
        // path opens the modal instead of the "View insight" toast. Not reset on
        // success by a reducer — the success listener must still read it as armed.
        pendingAddToDashboard: [
            false,
            {
                addToDashboard: (state) => (canCreateMetricsInsight() ? true : state),
                openAddToDashboardModal: () => false,
                saveAsInsightFailure: () => false,
            },
        ],
        // A real query failure (bad regex, 500, timeout) — surfaced as a banner so it isn't mistaken
        // for the empty-result state. Cleared when a new query starts or one succeeds; an aborted
        // (superseded) query leaves the previous state untouched so refetches don't flash an error.
        queryError: [
            null as string | null,
            {
                fetchQueryResults: () => null,
                fetchQueryResultsSuccess: () => null,
                fetchQueryResultsFailure: (state, { error }) =>
                    isUserInitiatedError(error) ? state : error || 'Something went wrong running this query.',
            },
        ],
        // Rides out superseded-query aborts, so the UI must read it instead of the auto
        // `queryResultsLoading`, which drops mid-refetch and flashes the empty state.
        queryLoading: [false as boolean, abortResilientLoading('fetchQueryResults')],
    }),
    listeners(({ actions, values, cache }) => {
        // Recovers each clause's type, and the aggregation that follows from it, when the metric
        // names were set before the picker's list arrived — the shape of a deep link on a cold
        // load. An already-latched type and an explicitly chosen aggregation are left alone.
        // Without the aggregation half, a link to a cumulative counter charts the raw running
        // total rather than its rate: nothing recommended an aggregation while the list was empty.
        const backfillClauseTypes = (): void => {
            const updates: MetricsViewerClauseBackfill[] = []
            values.viewerClauses.forEach((clause, index) => {
                const trimmedName = clause.metricName.trim()
                if (!trimmedName) {
                    return
                }
                const metricType = values.items.find((item) => item.name === trimmedName)?.metric_type
                const known = toKnownMetricType(metricType)
                const recommended = metricType ? RECOMMENDED_AGGREGATION_BY_TYPE[metricType] : undefined
                const update: MetricsViewerClauseBackfill = { index }
                if (known && clause.selectedMetricType === null) {
                    update.metricType = known
                }
                // The explicit-pick flag, not a compare against the default, is what holds a
                // deliberate choice — picking the default value is still a choice.
                if (recommended && !clause.aggregationExplicitlySet && recommended !== clause.aggregation) {
                    update.aggregation = recommended
                }
                if (update.metricType || update.aggregation) {
                    updates.push(update)
                }
            })
            if (updates.length) {
                actions.backfillClauses(updates)
            }
        }
        // Narrows the metric picker to the active clause's service chips, so it offers
        // only the metrics they report. The scope is compared before pushing so an
        // unrelated edit does not refetch the list.
        const syncPickerServices = (): void => {
            if (!objectsEqual(values.selectedServices, values.pickerServices)) {
                actions.setServices(values.selectedServices)
            }
        }
        return {
            // `setFilterGroup` changes the active clause's chips; the clause-navigation
            // actions change which clause's chips are the scope.
            setFilterGroup: syncPickerServices,
            setActiveClauseIndex: syncPickerServices,
            addClause: syncPickerServices,
            removeClause: syncPickerServices,
            duplicateClause: syncPickerServices,
            addAttributeFilter: ({ key, value }) => {
                const inner = values.filterGroup.values[0] as UniversalFiltersGroup
                const existingIndex = inner.values.findIndex(
                    (filter) =>
                        !isUniversalGroupFilterLike(filter) &&
                        'key' in filter &&
                        filter.key === key &&
                        'operator' in filter &&
                        filter.operator === PropertyOperator.Exact
                )
                const existing = existingIndex >= 0 ? (inner.values[existingIndex] as UniversalFilterValue) : null
                const existingValues = existing ? toValueStrings('value' in existing ? existing.value : null) : []
                if (existingValues.includes(value)) {
                    return
                }
                // Two chips on one key are ANDed, and no series equals both values, so a second pick of
                // the same key widens the chip it already has instead of adding another.
                const chip = {
                    type: PropertyFilterType.MetricAttribute,
                    key,
                    value: [...existingValues, value],
                    operator: PropertyOperator.Exact,
                }
                const nextValues = [...inner.values]
                if (existingIndex >= 0) {
                    nextValues[existingIndex] = chip as UniversalFilterValue
                } else {
                    nextValues.push(chip as UniversalFilterValue)
                }
                actions.setFilterGroup({
                    ...values.filterGroup,
                    values: [
                        { ...inner, values: nextValues as UniversalFiltersGroup['values'] },
                        ...values.filterGroup.values.slice(1),
                    ],
                })
            },
            setMetricName: ({ metricName }) => {
                const metricType = values.items.find((item) => item.name === metricName.trim())?.metric_type
                actions.setSelectedMetricType(toKnownMetricType(metricType))
                // Each metric type has one sensible default; a manual aggregation pick
                // holds only until the next metric switch.
                const recommended = metricType ? RECOMMENDED_AGGREGATION_BY_TYPE[metricType] : undefined
                if (recommended && recommended !== values.aggregation) {
                    actions.setRecommendedAggregation(recommended)
                }
            },
            loadItemsSuccess: backfillClauseTypes,
            // A URL restore replaces every clause at once and never ran the pick-time
            // latch, so it needs the same backfill against whatever the picker has.
            setClauses: () => {
                backfillClauseTypes()
                syncPickerServices()
            },
            saveAsInsightFailure: ({ error }) => {
                lemonToast.error(`Failed to save insight: ${error}`)
            },
            addToDashboard: () => {
                if (!canCreateMetricsInsight() || !values.metricsQueryNode) {
                    return
                }
                // Re-clicking with an unchanged query reuses the saved insight instead
                // of littering saved insights with duplicates.
                if (values.savedInsight && objectsEqual(values.lastSavedQueryNode, values.metricsQueryNode)) {
                    actions.openAddToDashboardModal()
                    return
                }
                actions.saveAsInsight()
            },
            saveAsInsightSuccess: ({ savedInsight }) => {
                if (savedInsight && values.pendingAddToDashboard) {
                    actions.openAddToDashboardModal()
                }
            },
            setGroupBySearch: () => {
                actions.loadAttributeKeyOptions({})
            },
            cancelInProgressQuery: ({ controller }) => {
                abortPrevious(values.queryAbortController)
                actions.setQueryAbortController(controller)
            },
            cancelInProgressAnomaly: ({ controller }) => {
                abortPrevious(values.anomalyAbortController)
                actions.setAnomalyAbortController(controller)
            },
            setLiveRefresh: ({ liveRefresh }) => {
                if (!liveRefresh) {
                    cache.disposables.dispose(LIVE_REFRESH_KEY)
                    return
                }
                // pauseOnPageHidden (default) stops polling on a hidden tab and resumes on focus.
                cache.disposables.add(() => {
                    const intervalId = setInterval(() => {
                        actions.fetchQueryResults({})
                        actions.fetchAnomaly({})
                    }, LIVE_REFRESH_MS)
                    return () => clearInterval(intervalId)
                }, LIVE_REFRESH_KEY)
            },
        }
    }),
    loaders(({ values, actions }) => ({
        // Backs the group-by attribute-key autocomplete. Scoped to the viewer's window so
        // suggestions match the data on screen; debounced to match the chart fetch cadence.
        attributeKeyOptions: [
            [] as { key: string; label: string }[],
            {
                loadAttributeKeyOptions: async (_, breakpoint) => {
                    if (!canViewMetrics()) {
                        return []
                    }
                    await breakpoint(300)
                    const dateFrom = resolveDate(values.dateFrom) ?? undefined
                    const dateTo = resolveDate(values.dateTo) ?? undefined
                    const response = await metricsAttributesRetrieve(String(values.currentTeamId), {
                        search: values.groupBySearch,
                        ...(dateFrom ? { dateFrom } : {}),
                        ...(dateTo ? { dateTo } : {}),
                        limit: 100,
                    })
                    breakpoint()
                    return response.results.map((result) => ({ key: result.name, label: result.name }))
                },
            },
        ],
        queryResults: [
            [] as MetricsViewerSeries[],
            {
                fetchQueryResults: async (_, breakpoint) => {
                    if (!canViewMetrics()) {
                        return []
                    }
                    const queryPayload = values.queryPayload
                    if (!queryPayload) {
                        return []
                    }
                    const dateFromISO = resolveDate(values.dateFrom)
                    if (!dateFromISO) {
                        return []
                    }
                    await breakpoint(300)
                    const dateToISO = resolveDate(values.dateTo) ?? undefined
                    const controller = new AbortController()
                    actions.cancelInProgressQuery(controller)
                    const response = await metricsQueryCreate(
                        String(values.currentTeamId),
                        {
                            query: {
                                ...queryPayload,
                                dateFrom: dateFromISO,
                                ...(dateToISO ? { dateTo: dateToISO } : {}),
                            },
                        },
                        { signal: controller.signal }
                    )
                    breakpoint()
                    actions.setQueryAbortController(null)
                    return response.results
                },
            },
        ],
        savedInsight: [
            null as QueryBasedInsightModel | null,
            {
                saveAsInsight: async () => {
                    if (!canCreateMetricsInsight()) {
                        return null
                    }
                    const query = values.metricsQueryNode
                    if (!query) {
                        return null
                    }
                    const insight = await insightsApi.create({
                        name: insightNameForViewerQuery(values.namedClauses, values.formula),
                        query,
                        saved: true,
                    })
                    actions.setLastSavedQueryNode(query)
                    // The add-to-dashboard flow opens the dashboard picker instead of a toast.
                    if (!values.pendingAddToDashboard) {
                        lemonToast.success('Insight saved', {
                            button: {
                                label: 'View insight',
                                action: () => router.actions.push(urls.insightView(insight.short_id)),
                            },
                        })
                    }
                    return insight
                },
            },
        ],
        anomalyReport: [
            null as _MetricAnomalyReportApi | null,
            {
                clearAnomaly: () => null,
                fetchAnomaly: async (_, breakpoint) => {
                    if (!canViewMetrics()) {
                        return null
                    }
                    // Null while suppressed (multi-series or formula): a badge computed from
                    // one input clause would be attributed to the wrong chart line.
                    const anomalyQuery = values.anomalyQuery
                    if (!anomalyQuery) {
                        return null
                    }
                    const fromISO = resolveDate(values.dateFrom)
                    if (!fromISO) {
                        return null
                    }
                    const toISO = resolveDate(values.dateTo) ?? dayjs().toISOString()
                    const spanMs = dayjs(toISO).diff(dayjs(fromISO))
                    if (spanMs <= 0) {
                        return null
                    }
                    const anomalyFrom = dayjs(toISO)
                        .subtract(spanMs * ANOMALY_WINDOW_FRACTION, 'ms')
                        .toISOString()
                    await breakpoint(300)
                    const controller = new AbortController()
                    actions.cancelInProgressAnomaly(controller)
                    const report = await metricsCharacterizeCreate(
                        String(values.currentTeamId),
                        {
                            query: {
                                ...anomalyQuery,
                                anomalyFrom,
                                anomalyTo: toISO,
                            },
                        },
                        { signal: controller.signal }
                    )
                    breakpoint()
                    actions.setAnomalyAbortController(null)
                    return report
                },
            },
        ],
    })),
    selectors({
        viewerClauses: [(s) => [s.queryState], (queryState: MetricsViewerQueryState) => queryState.clauses],
        activeClauseIndex: [
            (s) => [s.queryState],
            (queryState: MetricsViewerQueryState) => queryState.activeClauseIndex,
        ],
        formula: [(s) => [s.queryState], (queryState: MetricsViewerQueryState) => queryState.formula],
        activeClause: [
            (s) => [s.viewerClauses, s.activeClauseIndex],
            (clauses: MetricsViewerClause[], activeClauseIndex: number): MetricsViewerClause =>
                clauses[activeClauseIndex] ?? clauses[0],
        ],
        // The single-clause vocabulary, kept as selectors over the active clause so
        // everything that followed the viewer's one metric still works unchanged.
        metricName: [(s) => [s.activeClause], (activeClause: MetricsViewerClause) => activeClause.metricName],
        selectedMetricType: [
            (s) => [s.activeClause],
            (activeClause: MetricsViewerClause) => activeClause.selectedMetricType,
        ],
        aggregation: [(s) => [s.activeClause], (activeClause: MetricsViewerClause) => activeClause.aggregation],
        groupByKeys: [(s) => [s.activeClause], (activeClause: MetricsViewerClause) => activeClause.groupByKeys],
        filterGroup: [(s) => [s.activeClause], (activeClause: MetricsViewerClause) => activeClause.filterGroup],
        // The clauses that actually query something — a just-added blank row is
        // unsaved work in progress and stays out of every request and serialization.
        namedClauses: [
            (s) => [s.viewerClauses],
            (clauses: MetricsViewerClause[]): MetricsViewerClause[] =>
                clauses.filter((clause) => clause.metricName.trim().length > 0),
        ],
        hasMetricName: [(s) => [s.namedClauses], (namedClauses: MetricsViewerClause[]) => namedClauses.length > 0],
        // The chart request minus the date range (resolved at fetch time). The fetch
        // loader sends this object verbatim, so the fingerprint below can't drift from
        // the real payload. Null when nothing queries anything yet.
        queryPayload: [
            (s) => [s.namedClauses, s.formula],
            (namedClauses: MetricsViewerClause[], formula: string): MetricsQueryRequestBody | null =>
                namedClauses.length
                    ? { clauses: namedClauses.map(clauseToApiClause), ...(formula ? { formula } : {}) }
                    : null,
        ],
        // Effect key for the chart fetch: string-valued so equal queries compare equal,
        // and a blank-row add/remove (which changes `viewerClauses` but not the request)
        // doesn't refetch the chart and cascade into samples/exemplar reloads.
        queryFingerprint: [
            (s) => [s.queryPayload],
            (queryPayload: MetricsQueryRequestBody | null): string => JSON.stringify(queryPayload),
        ],
        // The characterize request minus the anomaly window, null when the badge is
        // suppressed: with several clauses (or a formula result) there is no single
        // input series it could honestly describe. Sent verbatim by the loader.
        anomalyQuery: [
            (s) => [s.namedClauses, s.formula],
            (namedClauses: MetricsViewerClause[], formula: string): MetricsAnomalyRequestBody | null => {
                if (namedClauses.length !== 1 || formula) {
                    return null
                }
                const clause = namedClauses[0]
                const filters = metricFiltersForGroup(clause.filterGroup)
                return {
                    metricName: clause.metricName.trim(),
                    aggregation: clause.aggregation,
                    ...(filters.length ? { filters } : {}),
                }
            },
        ],
        // Same idea as queryFingerprint: the badge only refetches when its own request
        // changes — a group-by edit redraws the chart but not the characterization.
        anomalyFingerprint: [
            (s) => [s.anomalyQuery],
            (anomalyQuery: MetricsAnomalyRequestBody | null): string => JSON.stringify(anomalyQuery),
        ],
        // Chart settings as they'd be persisted, with every default omitted — an all-defaults
        // object would change the shape of newly-saved nodes for no gain.
        metricsDisplay: [
            (s) => [s.displayType, s.goalLines, s.yAxisSettings],
            (
                displayType: MetricsDisplayType,
                goalLines: GoalLine[],
                yAxisSettings: MetricsYAxisSettings
            ): MetricsDisplaySettings | undefined => {
                const display: MetricsDisplaySettings = {
                    ...(displayType !== DEFAULT_DISPLAY_TYPE ? { type: displayType } : {}),
                    ...(goalLines.length ? { goalLines } : {}),
                    ...(Object.keys(yAxisSettings).length ? { yAxis: yAxisSettings } : {}),
                }
                return Object.keys(display).length ? display : undefined
            },
        ],
        // The viewer state as a `MetricsQuery` schema node — what "Save as insight"
        // persists, so the saved tile re-runs exactly what the viewer shows.
        metricsQueryNode: [
            (s) => [s.namedClauses, s.formula, s.dateFrom, s.dateTo, s.metricsDisplay],
            (
                namedClauses: MetricsViewerClause[],
                formula: string,
                dateFrom: string | null,
                dateTo: string | null,
                metricsDisplay: MetricsDisplaySettings | undefined
            ): MetricsQuery | null => {
                if (!namedClauses.length) {
                    return null
                }
                return {
                    kind: NodeKind.MetricsQuery,
                    clauses: namedClauses.map(clauseToNodeClause),
                    ...(formula ? { formula } : {}),
                    dateRange: {
                        date_from: dateFrom ?? DEFAULT_DATE_FROM,
                        ...(dateTo ? { date_to: dateTo } : {}),
                    },
                    ...(metricsDisplay ? { display: metricsDisplay } : {}),
                }
            },
        ],
        // The active clause's filter bar as backend matchers — what the samples panel sends.
        queryFilters: [
            (s) => [s.activeClause],
            (activeClause: MetricsViewerClause): _MetricFilterApi[] => metricFiltersForGroup(activeClause.filterGroup),
        ],
        // Services the metric picker is narrowed to, so it only offers metrics the
        // filtered services actually report. Empty means "every service".
        selectedServices: [
            (s) => [s.activeClause],
            (activeClause: MetricsViewerClause): string[] => {
                const chips = flattenFilterValues(activeClause.filterGroup).filter(
                    (filter) => 'key' in filter && filter.key === SERVICE_NAME_KEY
                )
                // Two service chips are ANDed, which no single IN list expresses, so
                // the picker stays unscoped rather than guessing at the intersection.
                if (chips.length !== 1) {
                    return []
                }
                return serviceChipValues(chips[0])
            },
        ],
        // Services the logs and traces pivots can be scoped to: the pinned service filter, or
        // failing that whichever services the chart is grouped by.
        correlationServices: [
            (s) => [s.selectedServices, s.queryResults],
            (selectedServices: string[], results: MetricsViewerSeries[]): string[] =>
                correlationServiceNames(
                    selectedServices,
                    results.map((series) => series.labels)
                ),
        ],
        // Scopes the filter bar's key/value suggestions to the viewer's window; splatted onto the
        // taxonomic endpoints as query params.
        attributeEndpointFilters: [
            (s) => [s.dateFrom, s.dateTo],
            (dateFrom: string | null, dateTo: string | null): Record<string, string> => ({
                ...(resolveDate(dateFrom) ? { dateFrom: resolveDate(dateFrom) as string } : {}),
                ...(resolveDate(dateTo) ? { dateTo: resolveDate(dateTo) as string } : {}),
            }),
        ],
        // All series rendered as chart lines (a group-by query returns one series per label combination).
        // `MetricsSeriesChart` owns naming and colors; this only bridges the API's snake_case fields.
        chartSeries: [
            (s) => [s.queryResults],
            (results: MetricsViewerSeries[]): MetricsChartSeries[] =>
                results.map((series) => ({
                    labels: series.labels,
                    points: series.points,
                    metricName: series.metric_name,
                    clause: series.clause,
                })),
        ],
        // Whether the chart has anything to draw. A query can return series with no points
        // in the selected window, which is the empty state rather than a plottable result.
        hasResults: [
            (s) => [s.queryResults],
            (results: MetricsViewerSeries[]): boolean => results.some((series) => series.points.length > 0),
        ],
        // The label values behind the current anomaly, ranked. Empty for an ungrouped metric or
        // when nothing stood out, which the panel reports rather than hiding.
        anomalyTopMovers: [
            (s) => [s.anomalyReport],
            (report: _MetricAnomalyReportApi | null): MetricTopMoverRow[] =>
                report ? topMoverRows(report.top_movers) : [],
        ],
        // Display shape for the anomaly badge — null when there's no report or the metric is flat.
        anomalyBadge: [
            (s) => [s.anomalyReport],
            (report: _MetricAnomalyReportApi | null): MetricsAnomalyBadge | null =>
                report && report.direction !== 'flat'
                    ? {
                          direction: report.direction,
                          percent: Math.abs(Math.round((report.change_ratio - 1) * 100)),
                          baselineMean: report.baseline_mean,
                          anomalyMean: report.anomaly_mean,
                          onsetTime: report.onset_time,
                      }
                    : null,
        ],
    }),
])
