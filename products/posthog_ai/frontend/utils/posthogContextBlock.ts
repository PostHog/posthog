import type { AttachedContextItem } from '../types/contextTypes'

/**
 * Standing instruction attached by the sidebar (foreground) surfaces — the ones where
 * `useMcpToolApplyBack` consumers can react to the run's tool calls. Tells the agent that tool calls
 * are how it acts on the app the user has open, so it calls tools instead of writing results as text.
 * Hidden from the composer's context chips; the static value means the task-scoped dedupe sends it
 * once per task resume chain.
 */
export const AGENT_TOOL_APPLY_BACK_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    value:
        'You are running alongside the PostHog app the user has open, and your PostHog MCP tool calls are how you act on it. ' +
        'When you complete a relevant tool call, its result is applied directly to what the user is looking at – for example, ' +
        'an open insight or SQL editor picks up the query from a completed query tool call. Be proactive about calling tools: ' +
        'when the user asks you to create or change something, achieve it with the matching tool call rather than only ' +
        'describing the result or writing it out as text. For example, if the user asks you to write SQL, call the ' +
        'execute-sql tool to write the query and verify it runs – the executed query lands in their open editor; never just ' +
        'print the SQL in your reply.',
}

/**
 * Renders attached context as a `<posthog_context>` block. The open/close tags MUST stay
 * byte-compatible with the backend template (`products/posthog_ai/backend/context_wrapper.py`) —
 * `runStreamLogic.unwrapUserMessageContent` strips on the tags, not the body, so both producers
 * (this frontend and the backend `attached_context` wrapper) round-trip identically.
 *
 * The body renders generically from the abstract shape — no per-type label map, arbitrary types
 * render as-is:
 *   - keyed items:  `- {type} {key} ("{label}")`  (key/label segments dropped when absent)
 *   - value items:  `- {type}: "{value}"`
 */
export function formatPosthogContextBlock(items: AttachedContextItem[]): string {
    const lines = [
        '<posthog_context>',
        'The user is currently looking at the following resources. ' +
            'Use the appropriate tools to retrieve their details only if relevant to the request.',
    ]
    for (const item of items) {
        lines.push(formatItem(item))
    }
    lines.push('</posthog_context>')
    return lines.join('\n')
}

/**
 * Invariant: interpolated fields must never contain the literal close-tag sequence.
 * `unwrapUserMessageContent` cuts at the FIRST '</posthog_context>', so a raw close tag inside the
 * body would truncate the strip early and leave block remnants on replay. Mirrors the backend
 * `_defang` in `context_wrapper.py`.
 */
function defang(text: string | number): string {
    return String(text).replace(/<\/posthog_context/g, '<\\/posthog_context')
}

function formatItem(item: AttachedContextItem): string {
    if (item.key === undefined || item.key === null || item.key === '') {
        return `- ${defang(item.type)}: "${defang(item.value ?? '')}"`
    }
    let line = `- ${defang(item.type)} ${defang(item.key)}`
    if (item.label) {
        line += ` ("${defang(item.label)}")`
    }
    return line
}

/** Prefixes `content` with the context block; returns `content` unchanged when `items` is empty. */
export function wrapWithPosthogContext(content: string, items: AttachedContextItem[]): string {
    if (items.length === 0) {
        return content
    }
    return `${formatPosthogContextBlock(items)}\n\n${content}`
}
