/**
 * Type definitions for text view parsing
 */

export interface TextSegment {
    type: 'text' | 'truncated' | 'gen_expandable' | 'tools_expandable'
    content: string
    fullContent?: string
    charCount?: number
    eventId?: string
}

export interface TextPart {
    type: 'text' | 'url'
    content: string
}

export interface EventLinkPart {
    type: 'event_link'
    eventId: string
    displayText: string
}
