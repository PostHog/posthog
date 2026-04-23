import { isCodingAgentClient } from '@/lib/client-detection'
import { formatResponse } from '@/lib/response'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, POSTHOG_META_KEY } from '@/tools/types'
import type { AnalyticsMetadata, WithAnalytics } from '@/ui-apps/types'

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
    /** The MCP `clientInfo.name` captured during `initialize`. */
    clientName: string | undefined
    /** PostHog distinctId for analytics metadata (only read when a UI resource is present). */
    distinctId?: string | undefined
}

export interface ToolResultPayload {
    content: Array<{ type: 'text'; text: string }>
    structuredContent?: Record<string, unknown>
}

/**
 * Assembles the MCP tool-call response payload.
 *
 * Two behaviors worth calling out:
 * 1. When the handler returns a primitive string, we pass it through to `formatResponse`
 *    unchanged. Earlier, object-rest on a string exploded it into a character-indexed
 *    dict ({"0":"{","1":"\""...}).
 * 2. When `formattedResults` is present AND the client is a coding-agent
 *    (e.g. Claude Code) AND the caller didn't opt into JSON via `output_format=json`,
 *    we drop `structuredContent`. Coding agents surface `structuredContent` to the model
 *    in preference to `content[].text`, so keeping it would hide the formatted table
 *    behind raw JSON.
 */
export function buildToolResultPayload(opts: BuildToolResultOptions): ToolResultPayload {
    const { handlerResult, toolMeta, toolName, params, clientName, distinctId } = opts

    const isStringResult = typeof handlerResult === 'string'
    const formattedResults: string | undefined = isStringResult
        ? undefined
        : ((handlerResult as Record<string, unknown> | null | undefined)?.[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY] as
              | string
              | undefined)

    let rawResult: Record<string, unknown> | string
    if (isStringResult) {
        rawResult = handlerResult as string
    } else {
        const { [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: _ignored, ...rest } = (handlerResult ?? {}) as Record<
            string,
            unknown
        >
        rawResult = rest
    }

    const hasUiResource = !!toolMeta?.ui?.resourceUri
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

    const text = formattedResults ?? (useJson ? JSON.stringify(rawResult) : formatResponse(rawResult))

    const suppressStructuredContent =
        formattedResults !== undefined && !callerWantsJson && isCodingAgentClient(clientName)

    return {
        content: [{ type: 'text', text }],
        ...(hasUiResource && !suppressStructuredContent
            ? { structuredContent: structuredContent as Record<string, unknown> }
            : {}),
    }
}
