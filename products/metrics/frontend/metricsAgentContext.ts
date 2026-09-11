import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/constants'

import { PropertyOperator, UniversalFiltersGroup } from '~/types'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import {
    DEFAULT_AGGREGATION,
    DEFAULT_DATE_FROM,
    MAX_CLAUSES,
    MetricAggregation,
    MetricsViewerClause,
    isMetricAggregation,
    sanitizeFormulaInput,
} from './components/metricsViewerLogic'
import { metricsFilterGroup } from './metricsLinks'

// Each visible chip and the hidden payload items it stands for share a dismiss group, so closing
// the chip actually detaches the payload instead of only hiding the chip.
const SKILL_DISMISS_GROUP = 'metrics-scene-skill'
const VIEWER_STATE_DISMISS_GROUP = 'metrics-scene-viewer-state'

const INVESTIGATING_METRIC_ANOMALIES_SKILL = 'investigating-metric-anomalies'

// All static strings below are our own build-time constants, which is what makes them safe to attach
// as trusted `instructions` items. The skill body and tool schemas are not embedded: product skills
// are installed in the agent's sandbox, and the exec MCP tool already exposes the metrics commands,
// so naming them is enough to skip discovery.
const PREAMBLE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value:
        'The user has the PostHog metrics (OpenTelemetry, Prometheus) viewer open. Load the ' +
        `${INVESTIGATING_METRIC_ANOMALIES_SKILL} skill before your first tool call; it covers which aggregation ` +
        'fits which metric type. Act through the metrics MCP tools: metric-names-list to resolve an exact metric ' +
        'name, query-metrics for the series, and characterize-metric-anomaly when the user reports that a metric ' +
        'looks wrong. Do not search for tools; use the exec `info <tool>` command when you need a full input schema.',
}

const SKILL_CHIP_CONTEXT_ITEM: AttachedContextItem = {
    type: 'skill',
    key: INVESTIGATING_METRIC_ANOMALIES_SKILL,
    label: 'Investigating metric anomalies skill',
    dismissGroup: SKILL_DISMISS_GROUP,
}

// Static: it names the fields the live state carries, so no user-entered metric name or filter value
// reaches trusted context. The viewer-state item's value changes with the query, so it always
// re-sends.
const APPLY_BACK_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: VIEWER_STATE_DISMISS_GROUP,
    value:
        'The metrics_viewer_state item is the current query of the open metrics viewer (its clauses with metric ' +
        'name, aggregation, group-by keys and filters, plus the formula, the date range and the open tab). When ' +
        'you call query-metrics, the query (metricName, aggregation, filters, groupBy, clauses, formula, dateFrom, ' +
        'dateTo) is also applied to the open viewer and the viewer tab opens, so the user sees the chart of what ' +
        'you queried. Read metrics_viewer_state before asking the user which metric they are looking at.',
}

export const METRICS_AGENT_HEADLINES: string[] = [
    'How can I help you investigate these metrics?',
    'Which metric are you trying to understand?',
]

export interface MetricsAgentViewerState {
    clauses: MetricsViewerClause[]
    formula: string
    dateFrom: string | null
    dateTo: string | null
    activeTab: string
}

// The viewer state the agent cannot fetch: the query on screen. Small by construction (up to ten
// clauses, each a metric name, an aggregation, a few keys and a filter group), so it rides along
// whole with no budgeting. It is an untrusted item, so user-typed metric names and filter values
// stay intact.
function serializeViewerState(state: MetricsAgentViewerState): string {
    return JSON.stringify({
        clauses: state.clauses.map((clause) => ({
            name: clause.name,
            metricName: clause.metricName,
            metricType: clause.selectedMetricType,
            aggregation: clause.aggregation,
            groupBy: clause.groupByKeys,
            filterGroup: clause.filterGroup,
        })),
        formula: state.formula,
        dateFrom: state.dateFrom,
        dateTo: state.dateTo,
        activeTab: state.activeTab,
    })
}

/**
 * The default agent context for the metrics scene: a pointer to the investigating-metric-anomalies
 * skill and the metrics MCP tools, an instruction that query-metrics calls reflect onto the open
 * page, and the live viewer query so the agent can read what the user is charting without a fetch.
 */
export function buildMetricsAgentContext(state: MetricsAgentViewerState): AttachedContextItem[] {
    return [
        PREAMBLE_CONTEXT_ITEM,
        SKILL_CHIP_CONTEXT_ITEM,
        APPLY_BACK_CONTEXT_ITEM,
        {
            type: 'metrics_viewer_state',
            hidden: true,
            dismissGroup: VIEWER_STATE_DISMISS_GROUP,
            value: serializeViewerState(state),
        },
    ]
}

/** The viewer query a query-metrics call maps onto, or null when the call named no metric to chart. */
export interface MetricsQueryApplyBack {
    clauses: MetricsViewerClause[]
    formula: string
    dateFrom: string | null
    dateTo: string | null
}

const FILTER_OP_TO_OPERATOR: Record<string, PropertyOperator> = {
    eq: PropertyOperator.Exact,
    neq: PropertyOperator.IsNot,
    regex: PropertyOperator.Regex,
    not_regex: PropertyOperator.NotRegex,
}

const CLAUSE_ALIASES = 'abcdefghij'

function asRecordArray(value: unknown): Record<string, unknown>[] {
    return Array.isArray(value)
        ? value.filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
        : []
}

function asString(value: unknown): string {
    return typeof value === 'string' ? value : ''
}

/**
 * The tool's aggregation vocabulary in the viewer's terms. The two quantile spellings the backend
 * accepts both land on the viewer's 'p95' shorthand, which is the only quantile a clause row can
 * show — a call for another quantile still charts the metric, at p95.
 */
function toViewerAggregation(value: unknown): MetricAggregation {
    if (isMetricAggregation(value)) {
        return value
    }
    return value === 'histogram_quantile' || value === 'quantile' ? 'p95' : DEFAULT_AGGREGATION
}

/** Label matchers as the filter bar's chips: one chip per matcher, ANDed, as the tool ran them. */
function toFilterGroup(filters: unknown): UniversalFiltersGroup {
    const chips = asRecordArray(filters)
        .map((filter) => ({
            key: asString(filter.key),
            value: [asString(filter.value)],
            operator: FILTER_OP_TO_OPERATOR[asString(filter.op)] ?? PropertyOperator.Exact,
        }))
        .filter((chip) => chip.key && chip.value[0])
    return chips.length > 0 ? metricsFilterGroup(chips) : DEFAULT_UNIVERSAL_GROUP_FILTER
}

function toGroupByKeys(groupBy: unknown): string[] {
    return asRecordArray(groupBy)
        .map((entry) => asString(entry.key))
        .filter(Boolean)
}

function toViewerClause(source: Record<string, unknown>, index: number): MetricsViewerClause | null {
    const metricName = asString(source.metricName).trim()
    if (!metricName) {
        return null
    }
    const requestedName = asString(source.name)
    return {
        // A clause alias must match the backend's identifier rules, and the formula below is
        // rewritten against these names, so an unusable alias falls back to its positional letter.
        name: /^[a-z][a-z0-9_]{0,63}$/.test(requestedName) ? requestedName : CLAUSE_ALIASES[index],
        metricName,
        // The picker backfills the metric type from the name; the tool input never carries one.
        selectedMetricType: null,
        aggregation: toViewerAggregation(source.aggregation),
        // The agent picked this aggregation deliberately, so the picker's late backfill must not
        // replace it with the metric type's recommendation.
        aggregationExplicitlySet: true,
        filterGroup: toFilterGroup(source.filters),
        groupByKeys: toGroupByKeys(source.groupBy),
    }
}

/**
 * Map a query-metrics tool input onto the viewer's query, mirroring what the tool charted onto the
 * open page. The args are raw agent-sent JSON (never zod-validated), so every field is coerced and
 * defaulted. Both request forms are handled: `clauses` (with an optional formula) and the
 * single-metric shorthand. Returns null when no clause names a metric, so a discovery call cannot
 * blank the chart the user is looking at.
 */
export function metricsQueryToViewerState(input: Record<string, unknown>): MetricsQueryApplyBack | null {
    // All query-metrics params are nested inside `query`; fall back to the raw input defensively.
    const query = (input.query && typeof input.query === 'object' ? input.query : input) as Record<string, unknown>

    const sources = Array.isArray(query.clauses) ? asRecordArray(query.clauses).slice(0, MAX_CLAUSES) : [query]
    const clauses = sources
        .map((source, index) => toViewerClause(source, index))
        .filter((clause): clause is MetricsViewerClause => clause !== null)
    if (clauses.length === 0) {
        return null
    }

    // A formula only means anything while every alias it references is on screen, and clauses the
    // mapping dropped take their aliases with them.
    const formula = clauses.length === sources.length ? sanitizeFormulaInput(asString(query.formula)) : ''

    return {
        clauses,
        formula,
        dateFrom: asString(query.dateFrom) || DEFAULT_DATE_FROM,
        dateTo: asString(query.dateTo) || null,
    }
}
