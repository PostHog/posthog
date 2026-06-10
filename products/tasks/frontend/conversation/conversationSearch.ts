import type { ConversationItem, RenderItem } from './buildConversationItems'

/** One occurrence of the query inside a conversation item's searchable text. */
export interface SearchMatch {
    itemIndex: number
    itemId: string
    occurrenceInItem: number
}

export const HIGHLIGHT_MATCH = 'search-match'
export const HIGHLIGHT_ACTIVE = 'search-match-active'

export function escapeRegExp(s: string): string {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function extractRenderItemText(update: RenderItem): string {
    switch (update.sessionUpdate) {
        case 'agent_message_chunk':
        case 'agent_thought_chunk':
            return 'content' in update && update.content.type === 'text' ? update.content.text : ''
        case 'console':
            return update.message
        case 'error':
            return update.message
        case 'status':
            return update.status
        case 'task_notification':
            return update.summary
        default:
            // Tool calls (and other structured updates) are excluded from search:
            // each tool renders its collapsed state differently, so extracted text
            // wouldn't match the DOM and counts would disagree with visible highlights.
            return ''
    }
}

export function extractSearchableText(item: ConversationItem): string {
    switch (item.type) {
        case 'user_message':
            return item.content
        case 'session_update':
            return extractRenderItemText(item.update)
        case 'user_shell_execute':
            return [item.command, item.result?.stdout ?? '', item.result?.stderr ?? ''].join(' ')
        case 'turn_cancelled':
            // Mirror TurnCancelledView's rendered copy so matches line up with the DOM.
            return item.interruptReason === 'moving_to_worktree'
                ? 'Paused while worktree is focused'
                : 'Interrupted by user'
        case 'queued':
            return item.message.content
        case 'git_action':
        case 'skill_button_action':
        case 'git_action_result':
            return ''
    }
}

export function findMatchesInItems(items: ConversationItem[], query: string): SearchMatch[] {
    if (!query) {
        return []
    }
    const re = new RegExp(escapeRegExp(query), 'gi')
    const matches: SearchMatch[] = []
    for (let i = 0; i < items.length; i++) {
        const text = extractSearchableText(items[i])
        if (!text) {
            continue
        }
        re.lastIndex = 0
        let occurrence = 0
        let m: RegExpExecArray | null = re.exec(text)
        while (m !== null) {
            matches.push({ itemIndex: i, itemId: items[i].id, occurrenceInItem: occurrence++ })
            if (m.index === re.lastIndex) {
                re.lastIndex++
            }
            m = re.exec(text)
        }
    }
    return matches
}

// ---------------------------------------------------------------------------
// DOM helpers — CSS Custom Highlight API
// ---------------------------------------------------------------------------

export function highlightsSupported(): boolean {
    return typeof CSS !== 'undefined' && typeof Highlight !== 'undefined' && !!CSS.highlights
}

export function clearHighlights(): void {
    if (!highlightsSupported()) {
        return
    }
    CSS.highlights.delete(HIGHLIGHT_MATCH)
    CSS.highlights.delete(HIGHLIGHT_ACTIVE)
}

export function findItemElement(container: HTMLElement, itemId: string): HTMLElement | null {
    // Attribute values can contain CSS-significant characters; compare directly instead of escaping a selector
    for (const el of container.querySelectorAll<HTMLElement>('[data-conversation-item-id]')) {
        if (el.getAttribute('data-conversation-item-id') === itemId) {
            return el
        }
    }
    return null
}

/** Text-node ranges matching the query within an item's rendered DOM. */
export function findRangesInItem(itemEl: HTMLElement, query: string): Range[] {
    const ranges: Range[] = []
    if (!query) {
        return ranges
    }
    const re = new RegExp(escapeRegExp(query), 'gi')
    const walker = document.createTreeWalker(itemEl, NodeFilter.SHOW_TEXT)
    while (walker.nextNode()) {
        const node = walker.currentNode
        const text = node.textContent ?? ''
        if (!text) {
            continue
        }
        re.lastIndex = 0
        let m: RegExpExecArray | null = re.exec(text)
        while (m !== null) {
            const range = new Range()
            range.setStart(node, m.index)
            range.setEnd(node, m.index + m[0].length)
            ranges.push(range)
            if (m.index === re.lastIndex) {
                re.lastIndex++
            }
            m = re.exec(text)
        }
    }
    return ranges
}

/**
 * Registers the `search-match` / `search-match-active` highlight sets for the
 * current matches. Returns the active match's Range (for scroll targeting), or
 * null when nothing was highlighted or the Highlight API is unavailable.
 */
export function applyHighlights(
    container: HTMLElement,
    query: string,
    matches: SearchMatch[],
    activeMatch: SearchMatch | null
): Range | null {
    if (!highlightsSupported()) {
        return null
    }
    clearHighlights()
    if (!query || matches.length === 0) {
        return null
    }

    const itemIds = new Set(matches.map((m) => m.itemId))
    const allRanges: Range[] = []
    let activeRange: Range | null = null

    for (const itemId of itemIds) {
        const itemEl = findItemElement(container, itemId)
        if (!itemEl) {
            continue
        }
        const domRanges = findRangesInItem(itemEl, query)
        allRanges.push(...domRanges)
        if (activeMatch && activeMatch.itemId === itemId && domRanges.length > 0) {
            // Pick the DOM occurrence matching the data-model occurrence. If the
            // DOM has fewer occurrences (e.g. markdown collapsed whitespace),
            // fall back to the last one.
            activeRange = domRanges[Math.min(activeMatch.occurrenceInItem, domRanges.length - 1)]
        }
    }

    if (allRanges.length > 0) {
        CSS.highlights.set(HIGHLIGHT_MATCH, new Highlight(...allRanges))
    }
    if (activeRange) {
        CSS.highlights.set(HIGHLIGHT_ACTIVE, new Highlight(activeRange))
    }
    return activeRange
}
