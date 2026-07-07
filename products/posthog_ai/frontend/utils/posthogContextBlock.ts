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
