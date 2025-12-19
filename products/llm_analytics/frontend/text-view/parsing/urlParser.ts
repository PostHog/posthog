/**
 * URL and event link parsing utilities
 */
import { EventLinkPart, TextPart, UrlMatch } from './types'

/**
 * Parse text to find URLs and event links, split into parts
 */
export function parseUrls(text: string, traceId?: string): Array<TextPart | EventLinkPart> {
    const parts: Array<TextPart | EventLinkPart> = []

    // Process event links first, then URLs
    const eventLinkRegex = /<<<EVENT_LINK\|([^|]+)\|([^>]+)>>>/g
    const urlRegex = /(https?:\/\/[^\s]+)/g

    let lastIndex = 0
    const matches: UrlMatch[] = []

    // Find all event links
    let eventMatch: RegExpExecArray | null
    while ((eventMatch = eventLinkRegex.exec(text)) !== null) {
        matches.push({
            index: eventMatch.index,
            length: eventMatch[0].length,
            type: 'event_link',
            data: { eventId: eventMatch[1], displayText: eventMatch[2] },
        })
    }

    // Find all URLs
    let urlMatch: RegExpExecArray | null
    while ((urlMatch = urlRegex.exec(text)) !== null) {
        matches.push({
            index: urlMatch.index,
            length: urlMatch[0].length,
            type: 'url',
            data: { content: urlMatch[1] },
        })
    }

    // Sort by index
    matches.sort((a, b) => a.index - b.index)

    // Build parts
    for (const match of matches) {
        // Add text before match
        if (match.index > lastIndex) {
            parts.push({
                type: 'text',
                content: text.slice(lastIndex, match.index),
            })
        }

        // Add the match
        if (match.type === 'url') {
            parts.push({
                type: 'url',
                content: match.data.content,
            })
        } else if (match.type === 'event_link' && traceId) {
            parts.push({
                type: 'event_link',
                eventId: match.data.eventId,
                displayText: match.data.displayText,
            })
        } else {
            // Fallback to text if no traceId
            parts.push({
                type: 'text',
                content: match.data.displayText || '',
            })
        }

        lastIndex = match.index + match.length
    }

    // Add remaining text
    if (lastIndex < text.length) {
        parts.push({
            type: 'text',
            content: text.slice(lastIndex),
        })
    }

    // If no matches found, return the whole text as one part
    if (parts.length === 0) {
        parts.push({
            type: 'text',
            content: text,
        })
    }

    return parts
}
