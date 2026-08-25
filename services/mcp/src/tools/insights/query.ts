import type { z } from 'zod'

import type { AccessControlFilterWarning, DataWarehouseSyncWarning } from '@/api/client'
import { withUiApp } from '@/resources/ui-apps'
import type { Insight } from '@/schema/insights'
import { InsightQueryInputSchema } from '@/schema/tool-inputs'
import { withAgentNote, withPostHogUrl, type WithAgentNote, type WithPostHogUrl } from '@/tools/tool-utils'
import { type Context, POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, type ToolBase } from '@/tools/types'

import { analyzeQuery } from '../shared'

const schema = InsightQueryInputSchema

/** The insight kinds `alert-create` accepts. Anything else cannot carry an alert. */
const ALERTABLE_QUERY_KINDS = new Set(['TrendsQuery', 'FunnelsQuery', 'HogQLQuery'])

const ALERT_AGENT_NOTE =
    "This response carries the insight's current value, so it is a good moment to offer an alert when the metric " +
    'is one someone would act on if it moved sharply (signups, active users, revenue, conversion rate, error or ' +
    'failure counts, latency). Name an actual number, never a placeholder such as X, for example "want me to ' +
    'alert you when daily signups drop below 400?". A count sitting at zero, such as errors or failures, is a ' +
    'strong case, so offer an upper bound of 1. Offer nothing when the insight returned no rows. When no absolute ' +
    'number fits, offer a relative-change alert, or preview an anomaly detector with alert-simulate and say how ' +
    'often it would have fired. Skip metrics nobody acts on, such as raw pageview or event-volume counts, and ' +
    'skip high-cardinality breakdowns. Judge the metric, not the request. A newly created insight, or one the ' +
    'user just asked to see, is not throwaway for that reason. If the user already declined an alert in this ' +
    'conversation, do not offer again.'

type Params = z.infer<typeof schema>

type Payload = WithPostHogUrl<{
    query: unknown
    insight: Insight & { url: string }
    results: unknown
    warnings?: (DataWarehouseSyncWarning | AccessControlFilterWarning)[] | null
    [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]?: string
}>

type Result = Payload | WithAgentNote<Payload>

// Accept either a pre-encoded JSON string or a plain object for the override
// params. LLM agents reading the insight-get response see `variables` as an
// object, so requiring them to JSON.stringify before sending is friction that
// frequently breaks (escaping, double-encoding). Normalising here lets either
// shape reach the backend as a properly-encoded query-string value.
//
// Transitional: the auto-generated tools rely on ApiClient.request() in
// services/mcp/src/api/client.ts, which already JSON-stringify-s object query
// params automatically. This helper exists because the bespoke insights().get()
// in client.ts builds its own URLSearchParams and types the override params as
// `string`. Once that endpoint migrates onto request(), normalizeOverride can
// be deleted.
function normalizeOverride(value: string | Record<string, unknown> | undefined): string | undefined {
    if (value === undefined) {
        return undefined
    }
    return typeof value === 'string' ? value : JSON.stringify(value)
}

export const queryHandler: ToolBase<typeof schema, Result>['handler'] = async (context: Context, params: Params) => {
    const { insightId, output_format, variables_override, filters_override } = params
    const projectId = await context.stateManager.getProjectId()

    const normalizedVariables = normalizeOverride(variables_override)
    const normalizedFilters = normalizeOverride(filters_override)

    // Threading overrides through the .get() call lets the Django retrieve endpoint
    // merge them server-side (via apply_dashboard_variables_to_dict /
    // apply_dashboard_filters_to_dict). The merged query is then POSTed to /query/
    // as-is, so insight-query results reflect the overridden values without
    // mutating the saved insight.
    const insightResult = await context.api.insights({ projectId }).get({
        insightId,
        variables_override: normalizedVariables,
        filters_override: normalizedFilters,
    })

    if (!insightResult.success) {
        throw new Error(`Failed to get insight: ${insightResult.error.message}`)
    }

    const queryResult = await context.api.insights({ projectId }).query({
        query: insightResult.data.query,
    })

    if (!queryResult.success) {
        throw new Error(`Failed to query insight: ${queryResult.error.message}`)
    }

    // Carry the overrides into the link as query params so opening the insight in
    // the UI reflects the same filtered/variabled view that was rendered — matching
    // the frontend's own `urls.insightView` encoding. Without this the link resolves
    // to the bare saved insight and silently drops the overrides.
    const overrideParams = [
        { key: 'variables_override', value: normalizedVariables },
        { key: 'filters_override', value: normalizedFilters },
    ]
        .filter((p): p is { key: string; value: string } => Boolean(p.value))
        .map((p) => `${p.key}=${encodeURIComponent(p.value)}`)
        .join('&')
    const path = `/insights/${insightResult.data.short_id}${overrideParams ? `?${overrideParams}` : ''}`
    const fullUrl = `${context.api.getProjectBaseUrl(projectId)}${path}`
    const queryInfo = analyzeQuery(insightResult.data.query)

    // Only HogQL/table results carry a separate `columns` array, so they're the only
    // shape the UI app wraps as `{ columns, results }`. Every chart visualizer
    // (trends, funnel, retention, lifecycle, stickiness, paths) consumes the raw
    // results array directly — wrapping those breaks the structural guards and renders
    // an empty table.
    const isTabular = queryInfo.visualization === 'table'
    const results = isTabular
        ? {
              columns: queryResult.data.columns || [],
              results: queryResult.data.results || [],
          }
        : queryResult.data.results

    // Optimized output surfaces the server-formatted summary as the model-facing text, but the
    // UI app still needs the structured results in structuredContent. Carry the formatted string
    // under the override key (which build-tool-result strips from structuredContent and uses as
    // the text payload) rather than overwriting `results` with it — mirrors query-wrapper-factory.
    const surfaceFormatted = output_format === 'optimized' && queryResult.data.formatted_results != null

    const payload = await withPostHogUrl(
        context,
        {
            query: queryInfo.innerQuery || insightResult.data.query,
            insight: {
                url: fullUrl,
                ...insightResult.data,
            },
            results,
            ...(queryResult.data.warnings ? { warnings: queryResult.data.warnings } : {}),
            ...(surfaceFormatted
                ? { [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: queryResult.data.formatted_results }
                : {}),
        },
        path
    )

    // The note offers an alert, so it is noise on an insight that already has one or cannot have one.
    const alerts = insightResult.data.alerts
    const hasAlert = Array.isArray(alerts) && alerts.length > 0
    if (hasAlert || !ALERTABLE_QUERY_KINDS.has(queryInfo.innerKind)) {
        return payload
    }
    return withAgentNote(payload, ALERT_AGENT_NOTE)
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('query-results', {
        name: 'insight-query',
        schema,
        handler: queryHandler,
    })
