import type { AttachedContextItem } from '../types/contextTypes'

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

function formatItem(item: AttachedContextItem): string {
    if (item.key === undefined || item.key === null || item.key === '') {
        return `- ${item.type}: "${item.value ?? ''}"`
    }
    let line = `- ${item.type} ${item.key}`
    if (item.label) {
        line += ` ("${item.label}")`
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
