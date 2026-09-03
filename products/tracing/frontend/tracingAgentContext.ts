import { DateRange } from '~/queries/schema/schema-general'
import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import {
    DEFAULT_DATE_RANGE,
    DEFAULT_ORDER_BY,
    DEFAULT_ORDER_DIRECTION,
    DEFAULT_VIEW_MODE,
    TracingFilters,
    TracingOrderBy,
    TracingOrderDirection,
} from './tracingFiltersLogic'

// Each visible chip and the hidden payload items it stands for share a dismiss group, so closing
// the chip actually detaches the payload instead of only hiding the chip.
const SKILL_DISMISS_GROUP = 'tracing-scene-skill'
const VIEWER_STATE_DISMISS_GROUP = 'tracing-scene-viewer-state'
const OPERATION_DISMISS_GROUP = 'tracing-operation-scene'

const EXPLORING_APM_TRACES_SKILL = 'exploring-apm-traces'

// All static strings below are our own build-time constants, which is what makes them safe to attach
// as trusted `instructions` items. The skill body and tool schemas are not embedded: product skills
// are installed in the agent's sandbox, and the exec MCP tool already exposes the tracing commands,
// so naming them is enough to skip discovery.
const PREAMBLE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value:
        'The user has the PostHog tracing (APM, OpenTelemetry spans) viewer open. Load the ' +
        `${EXPLORING_APM_TRACES_SKILL} skill before your first tool call; it covers the span fields and ` +
        'attributes you filter on. Act through the tracing MCP tools (the exec `apm-*` commands plus ' +
        'query-apm-spans: query-apm-spans, apm-trace-get, apm-spans-aggregate, apm-spans-count, ' +
        'apm-attribute-breakdown, apm-attributes-list, apm-services-list, and the rest). Do not search for ' +
        'tools; use the exec `info <tool>` command when you need a full input schema.',
}

const SKILL_CHIP_CONTEXT_ITEM: AttachedContextItem = {
    type: 'skill',
    key: EXPLORING_APM_TRACES_SKILL,
    label: 'Exploring traces skill',
    dismissGroup: SKILL_DISMISS_GROUP,
}

// Static: it names the fields the live state carries, so no user-entered filter value or trace id
// reaches trusted context. The viewer-state item's value changes with the filters, so it always
// re-sends.
const APPLY_BACK_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: VIEWER_STATE_DISMISS_GROUP,
    value:
        'The tracing_viewer_state item is the current filter state of the open tracing viewer (date range, ' +
        'service names, filter group, view mode, sort) and, when a trace drawer is open, its open_trace field ' +
        'names the trace and span the user is looking at. When you call query-apm-spans, the query filters ' +
        '(serviceNames, statusCodes, traceId, filterGroup, dateRange, orderBy, orderDirection, flatSpans) are also ' +
        'applied to the open viewer, so the user sees matching spans both in this chat and on screen. When you ' +
        'call apm-trace-get, that trace opens in the viewer drawer. Read tracing_viewer_state before asking the ' +
        'user what they are filtering on.',
}

export const TRACING_AGENT_HEADLINES: string[] = [
    'How can I help you investigate these traces?',
    'What are you trying to find in the traces?',
]

export interface TracingOpenTrace {
    traceId: string
    spanId: string | null
}

// The viewer state the agent cannot fetch: what the user is filtering on and which trace they have
// open. Small by construction (a date range, service names, a filter group, and two ids), so it
// rides along whole with no budgeting. It is an untrusted item, so user-typed filter values stay
// intact. Dragged comparison windows are ephemeral absolute-ms positions, so only mode and preset
// are sent.
function serializeViewerState(filters: TracingFilters, openTrace: TracingOpenTrace | null): string {
    return JSON.stringify({
        dateRange: filters.dateRange,
        serviceNames: filters.serviceNames,
        filterGroup: filters.filterGroup,
        viewMode: filters.viewMode,
        orderBy: filters.orderBy,
        orderDirection: filters.orderDirection,
        comparison: filters.comparison ? { mode: filters.comparison.mode, preset: filters.comparison.preset } : null,
        open_trace: openTrace ? { trace_id: openTrace.traceId, span_id: openTrace.spanId } : null,
    })
}

/**
 * Context for the tracing scene: a pointer to the exploring-apm-traces skill and the tracing MCP
 * tools, the instruction that tool calls reflect onto the open page, and the live viewer state so
 * the agent can read what the user is filtering on without a fetch.
 */
export function buildTracingAgentContext(
    filters: TracingFilters,
    openTrace: TracingOpenTrace | null
): AttachedContextItem[] {
    return [
        PREAMBLE_CONTEXT_ITEM,
        SKILL_CHIP_CONTEXT_ITEM,
        APPLY_BACK_CONTEXT_ITEM,
        {
            type: 'tracing_viewer_state',
            hidden: true,
            dismissGroup: VIEWER_STATE_DISMISS_GROUP,
            value: serializeViewerState(filters, openTrace),
        },
    ]
}

const OPERATION_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: OPERATION_DISMISS_GROUP,
    value:
        'The user has a single tracing operation open. The tracing_operation item names the service_name, the ' +
        'span name and the date range on screen. Requests about "this operation" mean spans with that name in ' +
        'that service: scope query-apm-spans and the aggregate tools with serviceNames and a span-type name ' +
        'filter, and use apm-spans-duration-histogram or apm-spans-latency-heatmap for its latency distribution.',
}

/**
 * Context for the single-operation scene: the same skill and tool pointer, plus an untrusted
 * pointer to the operation on screen so "this operation" resolves without the user restating it.
 */
export function buildTracingOperationAgentContext(
    serviceName: string,
    spanName: string,
    dateRange: DateRange
): AttachedContextItem[] {
    return [
        PREAMBLE_CONTEXT_ITEM,
        SKILL_CHIP_CONTEXT_ITEM,
        OPERATION_CONTEXT_ITEM,
        {
            type: 'tracing_operation',
            hidden: true,
            dismissGroup: OPERATION_DISMISS_GROUP,
            value: JSON.stringify({ service_name: serviceName, name: spanName, dateRange }),
        },
    ]
}

function asStringArray(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
}

function spanFilter(key: string, value: string[]): UniversalFiltersGroupValue {
    return { type: PropertyFilterType.Span, key, operator: PropertyOperator.Exact, value } as UniversalFiltersGroupValue
}

/**
 * Map query-apm-spans tool input onto the viewer's filter fields, mirroring what the tool queried
 * onto the open page. The args are the raw agent-sent JSON (never zod-validated), so every field
 * is coerced and defaulted. statusCodes and traceId have no viewer facet of their own, so they
 * fold into the filter group as span-column filters, the same way the facet rail writes them. An
 * omitted field resets to the viewer default so the page shows the query's results exactly, with
 * the same complete-query semantics the tool ran with.
 */
export function apmSpansQueryToViewerFilters(input: Record<string, unknown>): Partial<TracingFilters> {
    // All query-apm-spans params are nested inside `query`; fall back to the raw input defensively.
    const query = (input.query && typeof input.query === 'object' ? input.query : input) as Record<string, unknown>

    const flatValues: UniversalFiltersGroupValue[] = (Array.isArray(query.filterGroup) ? query.filterGroup : []).map(
        (filter) => {
            const f = filter as Record<string, unknown>
            return {
                ...f,
                type: (f.type as PropertyFilterType) || PropertyFilterType.SpanAttribute,
                operator: (f.operator as PropertyOperator) || PropertyOperator.Exact,
            } as UniversalFiltersGroupValue
        }
    )

    const statusCodes = (Array.isArray(query.statusCodes) ? query.statusCodes : [])
        .filter((code): code is number | string => typeof code === 'number' || typeof code === 'string')
        .map(String)
    if (statusCodes.length > 0) {
        flatValues.push(spanFilter('status_code', statusCodes))
    }
    if (typeof query.traceId === 'string' && query.traceId) {
        flatValues.push(spanFilter('trace_id', [query.traceId]))
    }

    const filterGroup: UniversalFiltersGroup = {
        type: FilterLogicalOperator.And,
        values: [{ type: FilterLogicalOperator.And, values: flatValues }],
    }

    const orderBy: TracingOrderBy =
        query.orderBy === 'timestamp' || query.orderBy === 'duration' ? query.orderBy : DEFAULT_ORDER_BY
    const orderDirection: TracingOrderDirection =
        query.orderDirection === 'ASC' || query.orderDirection === 'DESC'
            ? query.orderDirection
            : DEFAULT_ORDER_DIRECTION

    return {
        dateRange: (query.dateRange as DateRange) ?? DEFAULT_DATE_RANGE,
        serviceNames: asStringArray(query.serviceNames),
        filterGroup,
        orderBy,
        orderDirection,
        viewMode: query.flatSpans === true ? 'spans' : DEFAULT_VIEW_MODE,
    }
}

const HEX_TRACE_ID = /^[0-9a-f]{32}$/i

/** The trace id an apm-trace-get call fetched, or null when the raw agent input carries none. */
export function apmTraceGetToTraceId(input: Record<string, unknown>): string | null {
    const traceId = input.trace_id
    return typeof traceId === 'string' && HEX_TRACE_ID.test(traceId) ? traceId : null
}
