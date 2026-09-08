import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'

import { getDiscoveryHint } from '@/lib/discovery-hints'
import { estimateTokens } from '@/lib/estimate-tokens'
import { formatResponse } from '@/lib/response'
import { isPrepareConfirmedActionResult } from '@/tools/confirmed-action-runtime'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, POSTHOG_META_KEY } from '@/tools/types'
import { APP_DATA_META_KEY, type AnalyticsMetadata, type WithAnalytics } from '@/ui-apps/types'

export interface ToolResultMeta {
    ui?: { resourceUri?: string }
    [POSTHOG_META_KEY]?: { outputFormat?: 'optimized' | 'json' }
}

export interface BuildToolResultOptions {
    /** Raw return value from the tool handler (object or string). */
    handlerResult: unknown
    /** Tool-level `_meta` — determines UI app eligibility and JSON response flag. */
    toolMeta?: ToolResultMeta | undefined
    /** Tool name; embedded in analytics metadata for UI apps. */
    toolName: string
    /** The input params passed to the tool (used to read `output_format=json` escape hatch). */
    params: unknown
    /** Whether formatted-result text should win over structuredContent for this client profile. */
    suppressStructuredContentForFormattedResults?: boolean | undefined
    /**
     * For inline-exec UI-app hosts (PostHog Desktop, Claude Code, Cowork): when a compact
     * formatted table is available, drop top-level `structuredContent` toward the model so
     * it reads the compact table instead of the verbose JSON, and re-home the app payload
     * onto `_meta` for the UI app (see APP_DATA_META_KEY). When there is NO formatted table
     * the payload stays in the standard `structuredContent` field and the text channel gets
     * a pointer instead of a second copy of it. Overridden by an explicit `output_format`.
     */
    forceUiDataToMeta?: boolean | undefined
    /** PostHog distinctId for analytics metadata (only read when a UI resource is present). */
    distinctId?: string | undefined
    /**
     * When set, the inner tool's `_meta.ui.resourceUri` is placed on the response payload
     * under both the new (`ui.resourceUri`) and legacy (`ui/resourceUri`) keys. Used by the
     * single-exec wrapper to surface UI apps through the generic `exec` tool — clients only
     * see `exec` registered, so the UI metadata has to ride on the per-call response.
     * Moves the app payload only; says nothing about the text channel.
     */
    includeUiResponseMeta?: boolean
    /**
     * Append `UI_APP_RENDER_NOTE` to the text channel so the model states its
     * conclusion in text instead of repeating data the user already sees in
     * the app view. Separate from `includeUiResponseMeta` on purpose: a caller
     * can move the app payload without adding context text, or the reverse.
     */
    includeRenderNote?: boolean
}

/**
 * Nominal brand stamped on payloads assembled by the exec wrapper. Detection
 * is a field check rather than structural matching so regular tool handlers
 * that happen to return a `{content:[{type:'text',…}]}` shape can never
 * accidentally short-circuit the `buildToolResultPayload` pipeline.
 */
export const EXEC_BUILT_PAYLOAD = '__execBuiltPayload' as const

export interface ToolResultPayload {
    content: Array<{ type: 'text'; text: string }>
    structuredContent?: Record<string, unknown>
    _meta?: Record<string, unknown>
    [EXEC_BUILT_PAYLOAD]?: true
}

/**
 * Detects a payload already assembled by the exec wrapper so `MCP.registerTool`
 * can pass it through unchanged — re-running `buildToolResultPayload` would
 * object-rest-destructure its `content` / `structuredContent` fields.
 *
 * We require the exec brand (rather than detecting by shape) so future tool
 * handlers can't accidentally match and skip the pipeline (coding-agent
 * suppression, analytics injection, UI-resourceUri normalization, etc.).
 */
export function isToolCallPayload(value: unknown): value is ToolResultPayload {
    return (
        typeof value === 'object' && value !== null && (value as Record<string, unknown>)[EXEC_BUILT_PAYLOAD] === true
    )
}

/**
 * How the text channel of a payload was assembled: the body (data table,
 * JSON, or the structuredContent pointer) plus any footers, kept as pieces.
 * `buildToolResultPayload` records this at build time; `estimateResponseTokens`
 * reads it instead of cutting the joined string back apart.
 */
interface BuiltResponseText {
    /** True when the body is only the structuredContent pointer. */
    structuredContentOnly: boolean
    footers: string[]
}

const builtResponseText = new WeakMap<ToolResultPayload, BuiltResponseText>()

/** Stamp a payload as exec-built so `isToolCallPayload` recognizes it. */
export function markExecPayload(payload: ToolResultPayload): ToolResultPayload {
    const marked: ToolResultPayload = { ...payload, [EXEC_BUILT_PAYLOAD]: true }
    const built = builtResponseText.get(payload)
    if (built) {
        builtResponseText.set(marked, built)
    }
    return marked
}

/**
 * Placeholder that replaces the text content when the payload rides in
 * `structuredContent` alone (see `buildToolResultPayload`). Kept short and
 * literal so the model knows where to read the result from.
 */
export const STRUCTURED_CONTENT_ONLY_TEXT = "Full result is in this response's structuredContent field."

/**
 * Footer for inline-exec UI-app hosts. The system prompt already carries the
 * no-repeat rule, but some models only honor it when the note arrives with the data.
 */
export const UI_APP_RENDER_NOTE =
    'The user already sees this result as an interactive view in the conversation. State your conclusion in text and do not repeat this data in your reply.'

/**
 * Estimate output tokens from what the client receives, not the raw handler object
 * (TOON is smaller than JSON for tabular results). When the text body is only the
 * structuredContent pointer, count `structuredContent` and the footers the builder
 * appended, not the pointer — read from the pieces the builder recorded, never by
 * taking the joined text apart.
 */
export function estimateResponseTokens(response: ToolResultPayload): number {
    const built = builtResponseText.get(response)
    if (response.structuredContent && built?.structuredContentOnly) {
        return estimateTokens(response.structuredContent) + estimateTokens(built.footers.join('\n\n'))
    }
    return estimateTokens(response.content.map((part) => part.text).join(''))
}

/**
 * Assembles the MCP tool-call response payload.
 *
 * Two behaviors worth calling out:
 * 1. When the handler returns a primitive string, we pass it through to `formatResponse`
 *    unchanged. Earlier, object-rest on a string exploded it into a character-indexed
 *    dict ({"0":"{","1":"\""...}).
 * 2. When `formattedResults` is present AND the resolved client profile needs formatted
 *    text to win AND the caller didn't opt into JSON via `output_format=json`, we drop
 *    `structuredContent`. Coding agents surface `structuredContent` to the model in
 *    preference to `content[].text`, so keeping it would hide the formatted table
 *    behind raw JSON.
 * 3. Conversely, a UI tool with no `formattedResults` on an inline-exec UI host keeps
 *    `structuredContent` and drops the mirrored text, so the payload reaches the agent
 *    exactly once instead of once per channel.
 */
export function buildToolResultPayload(opts: BuildToolResultOptions): ToolResultPayload {
    const {
        handlerResult,
        toolMeta,
        toolName,
        params,
        suppressStructuredContentForFormattedResults,
        forceUiDataToMeta,
        distinctId,
        includeUiResponseMeta,
        includeRenderNote,
    } = opts

    const isStringResult = typeof handlerResult === 'string'
    const formattedResults: string | undefined = isStringResult
        ? undefined
        : ((handlerResult as Record<string, unknown> | null | undefined)?.[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY] as
              | string
              | undefined)

    let rawResult: Record<string, unknown> | unknown[] | string
    if (isStringResult) {
        rawResult = handlerResult as string
    } else if (Array.isArray(handlerResult)) {
        rawResult = [...handlerResult]
    } else {
        const { [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: _ignored, ...rest } = (handlerResult ?? {}) as Record<
            string,
            unknown
        >
        rawResult = rest
    }

    const resourceUri = toolMeta?.ui?.resourceUri
    const hasUiResource = !!resourceUri
    // Caller's per-call `output_format` wins over the tool's YAML default in `_meta`.
    const callerOutputFormat = (params as { output_format?: 'optimized' | 'json' } | undefined)?.output_format
    const effectiveOutputFormat = callerOutputFormat ?? toolMeta?.[POSTHOG_META_KEY]?.outputFormat
    const useJson = effectiveOutputFormat === 'json'
    const callerWantsJson = callerOutputFormat === 'json'

    let structuredContent: WithAnalytics<typeof rawResult> | typeof rawResult = rawResult
    if (hasUiResource && !isStringResult) {
        const analyticsMetadata: AnalyticsMetadata = {
            distinctId: distinctId ?? '',
            toolName,
        }
        structuredContent = {
            ...(rawResult as Record<string, unknown>),
            _analytics: analyticsMetadata,
        }
    }

    // Drop top-level structuredContent only when a compact formatted table exists to take
    // its place — otherwise the model would just read the full data as TOON text anyway, and
    // suppressing here only forces the app payload to be duplicated under a non-standard
    // `_meta` key (see below). With no formatted table we keep the standard structuredContent
    // field, which UI apps and MCP hosts already prefer. `output_format=json` overrides both.
    const suppressStructuredContent =
        !callerWantsJson &&
        formattedResults !== undefined &&
        (!!forceUiDataToMeta || !!suppressStructuredContentForFormattedResults)

    // Inline-exec UI hosts surface BOTH `content[].text` and `structuredContent` to the
    // model. A UI tool with no compact formatted table has nothing smaller to offer the
    // text channel, so mirroring the payload there hands the agent a second full copy of
    // the same rows. Carry it once, in `structuredContent` — the field the UI app reads
    // from too — and leave a pointer in the text. `output_format` opts back into the
    // mirrored serialization for callers that parse the text channel.
    const structuredContentOnly =
        !!forceUiDataToMeta && hasUiResource && !isStringResult && !useJson && formattedResults === undefined

    const body = structuredContentOnly
        ? STRUCTURED_CONTENT_ONLY_TEXT
        : (formattedResults ?? (useJson ? JSON.stringify(rawResult) : formatResponse(rawResult)))

    // Footers ride the text channel after the body. The pieces stay in a list
    // until the payload is built: `estimateResponseTokens` counts them from
    // this list, never by cutting the joined text apart.
    const footers: string[] = []

    // Discovery hints mirror how error responses carry `getToolRecoveryHint`.
    // Skipped when the caller asked for raw JSON (the text must stay
    // machine-parseable) and when the text is only the structuredContent
    // pointer (the model reads the structured field).
    if (!isStringResult && !useJson && !structuredContentOnly && !isPrepareConfirmedActionResult(handlerResult)) {
        const discoveryHint = getDiscoveryHint({ toolName, handlerResult })
        if (discoveryHint) {
            footers.push(discoveryHint)
        }
    }

    if (includeRenderNote && hasUiResource && !useJson) {
        footers.push(UI_APP_RENDER_NOTE)
    }

    const text = [body, ...footers].join('\n\n')

    const payload: ToolResultPayload = {
        content: [{ type: 'text', text }],
    }
    builtResponseText.set(payload, { structuredContentOnly, footers })
    if (hasUiResource && !suppressStructuredContent) {
        payload.structuredContent = structuredContent as Record<string, unknown>
    }
    if (includeUiResponseMeta && resourceUri) {
        payload._meta = {
            ui: { resourceUri },
            [RESOURCE_URI_META_KEY]: resourceUri,
        }
        // `structuredContent` was dropped so the model reads the compact formatted
        // table, but the UI app still needs the data to render. `_meta` is host-
        // and app-only (never surfaced to the model), so carry the app payload here
        // and let `useToolResult` hydrate from it. See APP_DATA_META_KEY.
        if (suppressStructuredContent && hasUiResource) {
            payload._meta[APP_DATA_META_KEY] = structuredContent as Record<string, unknown>
        }
    }
    // `-prepare` tools have no UI resource, so UI apps driving a confirmed action
    // read the hash from the app-only `_meta` channel instead of structuredContent.
    if (isPrepareConfirmedActionResult(handlerResult)) {
        payload._meta = {
            ...payload._meta,
            [APP_DATA_META_KEY]: rawResult as Record<string, unknown>,
        }
    }
    return payload
}
