/**
 * Segment parsing utilities for text view display
 * Handles parsing of TRUNCATED, GEN_EXPANDABLE, and TOOLS_EXPANDABLE markers
 */
import { decodeBase64Utf8 } from './textHelpers'
import { SegmentMatch, TextSegment } from './types'

/**
 * Parse text for TRUNCATED and TOOLS_EXPANDABLE markers (used for nested content)
 */
export function parseTruncatedSegments(text: string): TextSegment[] {
    const segments: TextSegment[] = []
    const truncatedRegex = /<<<TRUNCATED\|([^|]+)\|(\d+)>>>/g
    const toolsExpandableRegex = /<<<TOOLS_EXPANDABLE\|([^|]+)\|([^>]+)>>>/g

    const allMatches: Array<Extract<SegmentMatch, { type: 'truncated' | 'tools_expandable' }>> = []

    // Find all truncated markers
    let truncMatch: RegExpExecArray | null
    while ((truncMatch = truncatedRegex.exec(text)) !== null) {
        allMatches.push({
            index: truncMatch.index,
            length: truncMatch[0].length,
            type: 'truncated',
            data: { encodedContent: truncMatch[1], charCount: parseInt(truncMatch[2], 10) },
        })
    }

    // Find all tools expandable markers
    let toolsMatch: RegExpExecArray | null
    while ((toolsMatch = toolsExpandableRegex.exec(text)) !== null) {
        allMatches.push({
            index: toolsMatch.index,
            length: toolsMatch[0].length,
            type: 'tools_expandable',
            data: { displayText: toolsMatch[1], encodedContent: toolsMatch[2] },
        })
    }

    // Sort by index
    allMatches.sort((a, b) => a.index - b.index)

    let lastIndex = 0

    for (const match of allMatches) {
        // Add text before the marker
        if (match.index > lastIndex) {
            segments.push({
                type: 'text',
                content: text.slice(lastIndex, match.index),
            })
        }

        if (match.type === 'truncated') {
            // Add truncated segment
            try {
                const fullContent = decodeBase64Utf8(match.data.encodedContent)
                segments.push({
                    type: 'truncated',
                    content: `... (${match.data.charCount} chars truncated)`,
                    fullContent,
                    charCount: match.data.charCount,
                })
            } catch {
                // If decoding fails, show as regular text
                segments.push({
                    type: 'text',
                    content: text.slice(match.index, match.index + match.length),
                })
            }
        } else if (match.type === 'tools_expandable') {
            // Add tools expandable segment
            try {
                const fullContent = decodeBase64Utf8(match.data.encodedContent)
                segments.push({
                    type: 'tools_expandable',
                    content: match.data.displayText,
                    fullContent,
                })
            } catch {
                // If decoding fails, show as regular text
                segments.push({
                    type: 'text',
                    content: text.slice(match.index, match.index + match.length),
                })
            }
        }

        lastIndex = match.index + match.length
    }

    // Add remaining text
    if (lastIndex < text.length) {
        segments.push({
            type: 'text',
            content: text.slice(lastIndex),
        })
    }

    return segments
}

/**
 * Parse text to find truncation, generation expandable, and tools expandable markers and split into segments
 */
export function parseTextSegments(text: string): TextSegment[] {
    const segments: TextSegment[] = []

    // Combined regex to match TRUNCATED, GEN_EXPANDABLE, and TOOLS_EXPANDABLE markers
    const truncatedRegex = /<<<TRUNCATED\|([^|]+)\|(\d+)>>>/g
    const genExpandableRegex = /<<<GEN_EXPANDABLE\|([^|]+)\|([^|]+)\|([^>]+)>>>/g
    const toolsExpandableRegex = /<<<TOOLS_EXPANDABLE\|([^|]+)\|([^>]+)>>>/g

    const allMatches: SegmentMatch[] = []

    // Find all truncated markers
    let truncMatch: RegExpExecArray | null
    while ((truncMatch = truncatedRegex.exec(text)) !== null) {
        allMatches.push({
            index: truncMatch.index,
            length: truncMatch[0].length,
            type: 'truncated',
            data: { encodedContent: truncMatch[1], charCount: parseInt(truncMatch[2], 10) },
        })
    }

    // Find all gen expandable markers
    let genMatch: RegExpExecArray | null
    while ((genMatch = genExpandableRegex.exec(text)) !== null) {
        allMatches.push({
            index: genMatch.index,
            length: genMatch[0].length,
            type: 'gen_expandable',
            data: { eventId: genMatch[1], displayText: genMatch[2], encodedContent: genMatch[3] },
        })
    }

    // Find all tools expandable markers
    let toolsMatch: RegExpExecArray | null
    while ((toolsMatch = toolsExpandableRegex.exec(text)) !== null) {
        allMatches.push({
            index: toolsMatch.index,
            length: toolsMatch[0].length,
            type: 'tools_expandable',
            data: { displayText: toolsMatch[1], encodedContent: toolsMatch[2] },
        })
    }

    // Sort by index
    allMatches.sort((a, b) => a.index - b.index)

    let lastIndex = 0

    for (const match of allMatches) {
        // Add text before the marker
        if (match.index > lastIndex) {
            segments.push({
                type: 'text',
                content: text.slice(lastIndex, match.index),
            })
        }

        if (match.type === 'truncated') {
            // Add truncated segment
            try {
                const fullContent = decodeBase64Utf8(match.data.encodedContent)
                segments.push({
                    type: 'truncated',
                    content: `... (${match.data.charCount} chars truncated)`,
                    fullContent,
                    charCount: match.data.charCount,
                })
            } catch {
                // If decoding fails, show as regular text
                segments.push({
                    type: 'text',
                    content: text.slice(match.index, match.index + match.length),
                })
            }
        } else if (match.type === 'gen_expandable') {
            // Add gen expandable segment
            try {
                const fullContent = decodeBase64Utf8(match.data.encodedContent)
                segments.push({
                    type: 'gen_expandable',
                    content: match.data.displayText,
                    fullContent,
                    eventId: match.data.eventId,
                })
            } catch {
                // If decoding fails, show as regular text
                segments.push({
                    type: 'text',
                    content: text.slice(match.index, match.index + match.length),
                })
            }
        } else if (match.type === 'tools_expandable') {
            // Add tools expandable segment
            try {
                const fullContent = decodeBase64Utf8(match.data.encodedContent)
                segments.push({
                    type: 'tools_expandable',
                    content: match.data.displayText,
                    fullContent,
                })
            } catch {
                // If decoding fails, show as regular text
                segments.push({
                    type: 'text',
                    content: text.slice(match.index, match.index + match.length),
                })
            }
        }

        lastIndex = match.index + match.length
    }

    // Add remaining text
    if (lastIndex < text.length) {
        segments.push({
            type: 'text',
            content: text.slice(lastIndex),
        })
    }

    return segments
}
