/**
 * Bounds one tool result to what the calling client can actually accept.
 *
 * Clients cap the size of a single tool result and truncate anything larger
 * themselves, mid-value and without explanation, so the agent pays for a blob
 * it cannot parse. Shortening the response here instead keeps it valid JSON,
 * says what was left out, and tells the agent how to ask for less.
 *
 * The budget comes from the client profile (`maxResponseTokens`), because the
 * limits differ by an order of magnitude between harnesses.
 *
 * Only the channel the model reads is shortened, which is the same channel
 * `estimateResponseTokens` measures: the formatted text, or `structuredContent`
 * when the text is just a pointer to it. A `structuredContent` that mirrors the
 * text is host-rendered UI data rather than model context, so it is left alone.
 *
 * This is a client-boundary safeguard only. The underlying query and the
 * PostHog UI still hold the complete result.
 */

import { STRUCTURED_CONTENT_ONLY_TEXT, estimateResponseTokens, type ToolResultPayload } from '@/lib/build-tool-result'
import { CHARS_PER_TOKEN } from '@/lib/estimate-tokens'

/** Key the projection records its own shortening under, mirroring trace compaction. */
export const RESPONSE_TRUNCATION_KEY = '_truncated'

/**
 * Smallest projection worth returning. Below this a shortened response is
 * fragments rather than a usable head, so the notice alone is more honest.
 */
const MIN_PROJECTION_CHARS = 200

export interface CappedResponse {
    response: ToolResultPayload
    /** Estimated tokens of the response the client receives. */
    outputTokens: number
    /** Estimated tokens of the original response. Set only when the cap fired. */
    overflowTokens?: number
}

function formatTokens(tokens: number): string {
    return tokens >= 1000 ? `${Math.round(tokens / 1000)}K` : String(tokens)
}

function overflowNotice(tokens: number, maxTokens: number): string {
    return (
        `Result shortened to fit this client: the full result is about ${formatTokens(tokens)} tokens ` +
        `and the client accepts about ${formatTokens(maxTokens)} per tool result. ` +
        `To read the rest, ask for less at a time: add filters, shorten the date range, ` +
        `lower the limit, or request a narrower field or detail level.`
    )
}

function serializedChars(value: unknown): number {
    try {
        return JSON.stringify(value)?.length ?? Number.POSITIVE_INFINITY
    } catch {
        // Non-serializable value (circular refs, BigInt, ...) — unaffordable
        // rather than guessed at, so the projection drops it.
        return Number.POSITIVE_INFINITY
    }
}

/** Cost of one object entry: its quoted key, the colon, the value, and a comma. */
function entryChars(key: string, value: unknown): number {
    return JSON.stringify(key).length + serializedChars(value) + 2
}

/** Leading items of an array that fit the budget, as a whole number of items. */
function keepLeadingItems(items: unknown[], budget: number): { kept: unknown[]; chars: number } {
    const kept: unknown[] = []
    let chars = 2
    for (const item of items) {
        const cost = serializedChars(item) + 1
        if (chars + cost > budget) {
            break
        }
        kept.push(item)
        chars += cost
    }
    return { kept, chars }
}

/** Longest prefix of `text` within the budget, cut at a line boundary when a whole line fits. */
function clipText(text: string, budget: number): string {
    const head = text.slice(0, budget)
    const lastBreak = head.lastIndexOf('\n')
    // A row cut mid-value still reads as a whole row, so a partial line survives
    // only when no whole line fits at all — prose, or a single-line body.
    return lastBreak > 0 ? head.slice(0, lastBreak) : head
}

/**
 * The text channel as a JSON value, when it carries one. `output_format: 'json'`,
 * a tool that pins `outputFormat: 'json'`, and `exec --json` all return a
 * serialized value the caller parses, so shortening has to leave JSON behind —
 * clipping the string and appending a notice does not.
 */
function parseJsonText(text: string): Record<string, unknown> | unknown[] | undefined {
    const first = text.trimStart()[0]
    if (first !== '{' && first !== '[') {
        return undefined
    }
    try {
        const value: unknown = JSON.parse(text)
        return value !== null && typeof value === 'object' ? (value as Record<string, unknown> | unknown[]) : undefined
    } catch {
        return undefined
    }
}

/**
 * Keeps whole top-level entries while they fit, trims an oversized array to its
 * leading items, and skips anything still too large. Later entries are still
 * considered after a skip, so the short identity fields an agent navigates by
 * (`_posthogUrl`, ids, counts) survive even when the bulk payload does not.
 */
function projectRecord(
    record: Record<string, unknown>,
    budget: number
): { projected: Record<string, unknown>; omitted: string[]; shortened: string[] } {
    const projected: Record<string, unknown> = {}
    const omitted: string[] = []
    const shortened: string[] = []
    let spent = 2
    for (const [key, value] of Object.entries(record)) {
        const remaining = budget - spent
        const whole = entryChars(key, value)
        if (whole <= remaining) {
            projected[key] = value
            spent += whole
            continue
        }
        if (Array.isArray(value)) {
            const emptyArrayCost = entryChars(key, [])
            const { kept, chars } = keepLeadingItems(value, remaining - emptyArrayCost)
            if (kept.length > 0) {
                projected[key] = kept
                spent += emptyArrayCost + chars
                shortened.push(key)
                continue
            }
        }
        omitted.push(key)
    }
    return { projected, omitted, shortened }
}

/** `record` projected to the budget, with what it left out recorded inside the value. */
function projectRecordWithNotice(
    record: Record<string, unknown>,
    maxChars: number,
    notice: string
): Record<string, unknown> {
    const keys = Object.keys(record)
    // Reserve the worst-case truncation entry, with every key named in both
    // lists, so the projection plus its own bookkeeping stays inside the budget.
    const reserve = entryChars(RESPONSE_TRUNCATION_KEY, { notice, shortenedFields: keys, omittedFields: keys })
    const { projected, omitted, shortened } = projectRecord(record, Math.max(MIN_PROJECTION_CHARS, maxChars - reserve))
    return {
        ...projected,
        [RESPONSE_TRUNCATION_KEY]: {
            notice,
            ...(shortened.length > 0 ? { shortenedFields: shortened } : {}),
            ...(omitted.length > 0 ? { omittedFields: omitted } : {}),
        },
    }
}

/**
 * Leading items of `items` within the budget, closed by the same sentinel element
 * trace compaction appends to a shortened list. A list stays a list, so a caller
 * that parses the value still reads rows where it read rows before.
 */
function projectArrayWithNotice(items: unknown[], maxChars: number, notice: string): unknown[] {
    const sentinel = (omittedItems: number): Record<string, unknown> => ({
        [RESPONSE_TRUNCATION_KEY]: { notice, omittedItems, totalItems: items.length },
    })
    const reserve = serializedChars(sentinel(items.length)) + 1
    const { kept } = keepLeadingItems(items, Math.max(MIN_PROJECTION_CHARS, maxChars - reserve))
    return [...kept, sentinel(items.length - kept.length)]
}

/**
 * Shorten `response` to `maxTokens` if it is larger. Returns the response
 * untouched when it fits, or when no budget is set for the client.
 */
export function capResponseToClientBudget(response: ToolResultPayload, maxTokens: number | undefined): CappedResponse {
    const tokens = estimateResponseTokens(response)
    if (!maxTokens || !Number.isFinite(maxTokens) || tokens <= maxTokens) {
        return { response, outputTokens: tokens }
    }

    const notice = overflowNotice(tokens, maxTokens)
    const maxChars = maxTokens * CHARS_PER_TOKEN
    let capped: ToolResultPayload

    const text = response.content.map((part) => part.text).join('')
    const structuredContent = text === STRUCTURED_CONTENT_ONLY_TEXT ? response.structuredContent : undefined
    const jsonValue = structuredContent ? undefined : parseJsonText(text)
    if (structuredContent) {
        capped = { ...response, structuredContent: projectRecordWithNotice(structuredContent, maxChars, notice) }
    } else if (jsonValue !== undefined) {
        const projected = Array.isArray(jsonValue)
            ? projectArrayWithNotice(jsonValue, maxChars, notice)
            : projectRecordWithNotice(jsonValue, maxChars, notice)
        capped = { ...response, content: [{ type: 'text', text: JSON.stringify(projected) }] }
    } else {
        // The notice, plus the blank line separating it from the kept text.
        const budget = Math.max(MIN_PROJECTION_CHARS, maxChars - notice.length - 2)
        capped = { ...response, content: [{ type: 'text', text: `${clipText(text, budget)}\n\n${notice}` }] }
    }

    return { response: capped, outputTokens: estimateResponseTokens(capped), overflowTokens: tokens }
}
