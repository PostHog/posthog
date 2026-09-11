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
    toKnownMetricType,
} from './components/metricsViewerLogic'
import { metricsFilterGroup } from './metricsLinks'

// A chip and the hidden items it stands for share a dismiss group, so closing it detaches them too.
const SKILL_DISMISS_GROUP = 'metrics-scene-skill'
const VIEWER_STATE_DISMISS_GROUP = 'metrics-scene-viewer-state'

const INVESTIGATING_METRIC_ANOMALIES_SKILL = 'investigating-metric-anomalies'

// Only our own build-time strings may ride in a trusted `instructions` item. The skill body and
// tool schemas stay out: both are already reachable in the agent's sandbox, so naming them suffices.
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

// Names the fields the live state carries, so no user-entered value reaches trusted context.
const APPLY_BACK_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: VIEWER_STATE_DISMISS_GROUP,
    value:
        'The metrics_viewer_state item is the current query of the open metrics viewer (its clauses with metric ' +
        'name, aggregation, group-by keys and filters, plus the formula, the date range and the open tab). When ' +
        'you call query-metrics, the query (metricName, metricType, aggregation, filters, groupBy, clauses, ' +
        'formula, dateFrom, dateTo) is also applied to the open viewer and the viewer tab opens, so the user sees ' +
        'the chart of what you queried. The viewer cannot show a quantile other than 0.95, an explicit filter or ' +
        'groupBy scope, or an explicit interval, so a query using one of those leaves the open chart untouched — ' +
        'do not tell the user their chart changed. Read metrics_viewer_state before asking the user which metric ' +
        'they are looking at.',
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

// The one thing the agent cannot fetch: the query on screen. Bounded by MAX_CLAUSES, so it rides
// along whole with no budgeting, and stays untrusted so user-typed names and values survive intact.
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

// One letter per clause the backend allows, so a positional fallback alias always exists.
const CLAUSE_ALIASES = 'abcdefghij'
const CLAUSE_NAME_PATTERN = /^[a-z][a-z0-9_]{0,63}$/
// The only quantile a clause row can show, as `nodeAggregationFields` sends it.
const VIEWER_QUANTILE = 0.95

function asRecordArray(value: unknown): Record<string, unknown>[] {
    return Array.isArray(value)
        ? value.filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
        : []
}

function asString(value: unknown): string {
    return typeof value === 'string' ? value : ''
}

function isQuantileAggregation(value: unknown): boolean {
    return value === 'histogram_quantile' || value === 'quantile'
}

/**
 * Whether a clause row can run this clause as the tool ran it. It has no control for a quantile
 * other than p95, and none for a filter or group-by scope, so mapping one of those would chart a
 * different query than the one that produced the agent's answer.
 */
function isRepresentableInViewer(source: Record<string, unknown>): boolean {
    if (isQuantileAggregation(source.aggregation) && source.quantile !== VIEWER_QUANTILE) {
        return false
    }
    const scoped = [...asRecordArray(source.filters), ...asRecordArray(source.groupBy)]
    return scoped.every((entry) => !asString(entry.scope) || entry.scope === 'auto')
}

function toViewerAggregation(value: unknown): MetricAggregation {
    if (isMetricAggregation(value)) {
        return value
    }
    return isQuantileAggregation(value) ? 'p95' : DEFAULT_AGGREGATION
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

interface ViewerClauses {
    clauses: MetricsViewerClause[]
    /** The tool's clause name, lowercased, to the alias the viewer gave it. Keys the formula rewrite. */
    aliasByToolName: Map<string, string>
}

function toViewerClauses(sources: Record<string, unknown>[]): ViewerClauses {
    const clauses: MetricsViewerClause[] = []
    const aliasByToolName = new Map<string, string>()
    const taken = new Set<string>()

    for (const source of sources) {
        const metricName = asString(source.metricName).trim()
        if (!metricName) {
            continue
        }
        // Lowercased because the formula is, and the two have to still match after the rewrite.
        const toolName = asString(source.name).toLowerCase()
        const free = [...CLAUSE_ALIASES].find((letter) => !taken.has(letter))
        // An alias the backend would reject, or one already spent, falls back to a free letter.
        const alias = CLAUSE_NAME_PATTERN.test(toolName) && !taken.has(toolName) ? toolName : free
        if (!alias) {
            continue
        }
        taken.add(alias)
        // First writer wins: a repeated tool name is ambiguous, so the formula follows the first clause.
        if (toolName && !aliasByToolName.has(toolName)) {
            aliasByToolName.set(toolName, alias)
        }
        clauses.push({
            name: alias,
            metricName,
            selectedMetricType: toKnownMetricType(asString(source.metricType) || undefined),
            aggregation: toViewerAggregation(source.aggregation),
            // A deliberate pick, so the picker's late backfill must not overwrite it.
            aggregationExplicitlySet: true,
            filterGroup: toFilterGroup(source.filters),
            groupByKeys: toGroupByKeys(source.groupBy),
        })
    }
    return { clauses, aliasByToolName }
}

/**
 * The formula in the viewer's aliases. Returns '' when it names a clause the mapping renamed away
 * or dropped, because the backend rejects a formula referencing a clause the query does not carry.
 */
function rewriteFormula(formula: string, aliasByToolName: Map<string, string>): string {
    let unresolved = false
    const rewritten = formula.replace(/[a-z][a-z0-9_]*/g, (token) => {
        const alias = aliasByToolName.get(token)
        if (!alias) {
            unresolved = true
            return token
        }
        return alias
    })
    return unresolved ? '' : rewritten
}

/**
 * Map a query-metrics tool input onto the viewer's query, mirroring what the tool charted onto the
 * open page. The args are raw agent-sent JSON (never zod-validated), so every field is coerced and
 * defaulted. Both request forms are handled: `clauses` (with an optional formula) and the
 * single-metric shorthand.
 *
 * Returns null rather than charting something the tool did not run: when no clause names a metric,
 * when a clause uses a quantile or scope the viewer cannot express, and when the call pins the
 * bucket interval, which the viewer always picks itself and which scales a per-bucket aggregate.
 */
export function metricsQueryToViewerState(input: Record<string, unknown>): MetricsQueryApplyBack | null {
    // All query-metrics params are nested inside `query`; fall back to the raw input defensively.
    const query = (input.query && typeof input.query === 'object' ? input.query : input) as Record<string, unknown>

    const sources = Array.isArray(query.clauses) ? asRecordArray(query.clauses).slice(0, MAX_CLAUSES) : [query]
    if (asString(query.interval) || !sources.every(isRepresentableInViewer)) {
        return null
    }

    const { clauses, aliasByToolName } = toViewerClauses(sources)
    if (clauses.length === 0) {
        return null
    }

    return {
        clauses,
        formula: rewriteFormula(sanitizeFormulaInput(asString(query.formula)), aliasByToolName),
        dateFrom: asString(query.dateFrom) || DEFAULT_DATE_FROM,
        dateTo: asString(query.dateTo) || null,
    }
}
