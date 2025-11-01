/**
 * Text view display component for generation events
 * Shows a formatted text representation with copy functionality and expandable truncated sections
 */
import { useEffect, useState } from 'react'

import { IconCopy, IconExternal } from '@posthog/icons'
import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { formatTraceTextRepr } from './formatters/traceFormatter'
import { formatEventTextRepr } from './textFormatter'

interface TextSegment {
    type: 'text' | 'truncated' | 'gen_expandable'
    content: string
    fullContent?: string
    charCount?: number
    eventId?: string
}

/**
 * Parse text for only TRUNCATED markers (used for nested content)
 */
function parseTruncatedSegments(text: string): TextSegment[] {
    const segments: TextSegment[] = []
    const truncatedRegex = /<<<TRUNCATED\|([^|]+)\|(\d+)>>>/g

    let lastIndex = 0
    let truncMatch: RegExpExecArray | null

    while ((truncMatch = truncatedRegex.exec(text)) !== null) {
        // Add text before the marker
        if (truncMatch.index > lastIndex) {
            segments.push({
                type: 'text',
                content: text.slice(lastIndex, truncMatch.index),
            })
        }

        // Add truncated segment
        try {
            const fullContent = decodeURIComponent(atob(truncMatch[1]))
            segments.push({
                type: 'truncated',
                content: `... (${parseInt(truncMatch[2], 10)} chars truncated)`,
                fullContent,
                charCount: parseInt(truncMatch[2], 10),
            })
        } catch {
            // If decoding fails, show as regular text
            segments.push({
                type: 'text',
                content: truncMatch[0],
            })
        }

        lastIndex = truncMatch.index + truncMatch[0].length
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
 * Parse text to find truncation and generation expandable markers and split into segments
 */
function parseTextSegments(text: string): TextSegment[] {
    const segments: TextSegment[] = []

    // Combined regex to match both TRUNCATED and GEN_EXPANDABLE markers
    const truncatedRegex = /<<<TRUNCATED\|([^|]+)\|(\d+)>>>/g
    const genExpandableRegex = /<<<GEN_EXPANDABLE\|([^|]+)\|([^|]+)\|([^>]+)>>>/g

    const allMatches: Array<{ index: number; length: number; type: 'truncated' | 'gen_expandable'; data: any }> = []

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
                const fullContent = decodeURIComponent(atob(match.data.encodedContent))
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
                const fullContent = decodeURIComponent(atob(match.data.encodedContent))
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
 * Get plain text representation for copying (with all truncated sections collapsed)
 */
function getPlainText(segments: TextSegment[]): string {
    return segments.map((seg) => (seg.type === 'truncated' ? seg.content : seg.content)).join('')
}

interface TextPart {
    type: 'text' | 'url'
    content: string
}

interface EventLinkPart {
    type: 'event_link'
    eventId: string
    displayText: string
}

/**
 * Parse text to find URLs and event links, split into parts
 */
function parseUrls(text: string, traceId?: string): Array<TextPart | EventLinkPart> {
    const parts: Array<TextPart | EventLinkPart> = []

    // Process event links first, then URLs
    const eventLinkRegex = /<<<EVENT_LINK\|([^|]+)\|([^>]+)>>>/g
    const urlRegex = /(https?:\/\/[^\s]+)/g

    let lastIndex = 0
    const matches: Array<{ index: number; length: number; type: 'url' | 'event_link'; data: any }> = []

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

/**
 * Render text with clickable URLs and event links
 */
function renderTextWithLinks(text: string, traceId?: string): JSX.Element[] {
    const parts = parseUrls(text, traceId)
    return parts.map((part, i) => {
        if (part.type === 'url') {
            return (
                <Link key={i} to={part.content} target="_blank" targetBlankIcon>
                    {part.content}
                </Link>
            )
        }
        if (part.type === 'event_link' && traceId) {
            return (
                <Link key={i} to={urls.llmAnalyticsTrace(traceId, { event: part.eventId })}>
                    {part.displayText}
                </Link>
            )
        }
        // Must be TextPart
        return <span key={i}>{(part as TextPart).content}</span>
    })
}

interface TraceTreeNode {
    event: any
    children?: TraceTreeNode[]
}

/**
 * Render content that may contain truncated segments (used for nested content)
 */
function NestedContentRenderer({
    content,
    traceId,
    parentKey,
    expandedSegments,
    setExpandedSegments,
    popoutSegment,
    setPopoutSegment,
}: {
    content: string
    traceId?: string
    parentKey: string
    expandedSegments: Set<string>
    setExpandedSegments: React.Dispatch<React.SetStateAction<Set<string>>>
    popoutSegment: string | null
    setPopoutSegment: React.Dispatch<React.SetStateAction<string | null>>
}): JSX.Element {
    const nestedSegments = parseTruncatedSegments(content)

    const toggleNestedSegment = (nestedIndex: number): void => {
        const key = `${parentKey}-${nestedIndex}`
        setExpandedSegments((prev) => {
            const next = new Set(prev)
            if (next.has(key)) {
                next.delete(key)
            } else {
                next.add(key)
            }
            return next
        })
    }

    const toggleNestedPopout = (nestedIndex: number): void => {
        const key = `${parentKey}-${nestedIndex}`
        setPopoutSegment((prev) => (prev === key ? null : key))
    }

    return (
        <>
            {nestedSegments.map((nestedSeg, nestedIdx) => {
                const nestedKey = `${parentKey}-${nestedIdx}`
                const isNestedExpanded = expandedSegments.has(nestedKey)
                const isNestedPopoutOpen = popoutSegment === nestedKey

                if (nestedSeg.type === 'text') {
                    return <span key={nestedIdx}>{renderTextWithLinks(nestedSeg.content, traceId)}</span>
                }

                // Truncated segment
                return (
                    <span key={nestedIdx}>
                        {isNestedExpanded ? (
                            <>
                                {renderTextWithLinks(nestedSeg.fullContent || '', traceId)}
                                <button
                                    onClick={() => toggleNestedSegment(nestedIdx)}
                                    className="text-link hover:underline cursor-pointer ml-1"
                                >
                                    [collapse]
                                </button>
                            </>
                        ) : (
                            <>
                                <button
                                    onClick={() => toggleNestedSegment(nestedIdx)}
                                    className="text-link hover:underline cursor-pointer"
                                >
                                    {nestedSeg.content}
                                </button>
                                <Tooltip
                                    title={
                                        isNestedPopoutOpen ? (
                                            <div
                                                data-popout-content
                                                className="max-h-96 overflow-auto whitespace-pre-wrap font-mono text-xs"
                                            >
                                                {nestedSeg.fullContent}
                                            </div>
                                        ) : null
                                    }
                                    containerClassName="max-w-4xl"
                                    placement="top"
                                    visible={isNestedPopoutOpen}
                                >
                                    <button
                                        data-popout-button
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            toggleNestedPopout(nestedIdx)
                                        }}
                                        className="inline-flex items-center justify-center w-4 h-4 ml-1 text-muted hover:text-default transition-colors"
                                        title="Preview truncated content"
                                    >
                                        <IconExternal className="w-3 h-3" />
                                    </button>
                                </Tooltip>
                            </>
                        )}
                    </span>
                )
            })}
        </>
    )
}

export function TextViewDisplay({
    event,
    trace,
    tree,
}: {
    event?: LLMTraceEvent
    trace?: LLMTrace
    tree?: TraceTreeNode[]
}): JSX.Element {
    const [copied, setCopied] = useState(false)

    // Get trace ID for event links
    const traceId = trace?.id

    // Determine what to display
    const textRepr =
        trace && tree
            ? formatTraceTextRepr(trace, tree) // Full trace view
            : event
              ? formatEventTextRepr(event) // Single event view
              : ''

    const segments = parseTextSegments(textRepr)
    const [expandedSegments, setExpandedSegments] = useState<Set<number | string>>(new Set())
    const [popoutSegment, setPopoutSegment] = useState<number | string | null>(null)

    // Get indices of all truncated and gen_expandable segments
    const truncatedIndices = segments
        .map((seg, idx) => (seg.type === 'truncated' ? idx : -1))
        .filter((idx) => idx !== -1)

    const genExpandableIndices = segments
        .map((seg, idx) => (seg.type === 'gen_expandable' ? idx : -1))
        .filter((idx) => idx !== -1)

    const allExpandableIndices = [...truncatedIndices, ...genExpandableIndices]

    const allExpanded =
        allExpandableIndices.length > 0 && allExpandableIndices.every((idx) => expandedSegments.has(idx))

    // Close popout when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent): void => {
            // Close if clicking outside and popout is open
            if (popoutSegment !== null) {
                const target = event.target as HTMLElement
                // Don't close if clicking on the tooltip or the button
                if (!target.closest('[data-popout-content]') && !target.closest('[data-popout-button]')) {
                    setPopoutSegment(null)
                }
            }
        }

        if (popoutSegment !== null) {
            document.addEventListener('mousedown', handleClickOutside)
            return () => {
                document.removeEventListener('mousedown', handleClickOutside)
            }
        }
    }, [popoutSegment])

    const handleCopy = (): void => {
        const plainText = getPlainText(segments)
        copyToClipboard(plainText, 'generation text')
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
    }

    const toggleSegment = (index: number): void => {
        setExpandedSegments((prev) => {
            const next = new Set(prev)
            if (next.has(index)) {
                next.delete(index)
            } else {
                next.add(index)
            }
            return next
        })
    }

    const toggleExpandAll = (): void => {
        if (allExpanded) {
            // Collapse all
            setExpandedSegments(new Set())
        } else {
            // Expand all (both truncated and gen_expandable segments)
            setExpandedSegments(new Set(allExpandableIndices))
        }
    }

    const togglePopout = (index: number): void => {
        setPopoutSegment((prev) => (prev === index ? null : index))
    }

    return (
        <div className="relative">
            <div className="absolute top-2 right-2 z-10 flex gap-2">
                {allExpandableIndices.length > 0 && (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={toggleExpandAll}
                        tooltip={allExpanded ? 'Collapse all expandable sections' : 'Expand all expandable sections'}
                    >
                        {allExpanded ? 'Collapse all' : 'Expand all'}
                    </LemonButton>
                )}
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconCopy />}
                    onClick={handleCopy}
                    tooltip={copied ? 'Copied!' : 'Copy text representation'}
                >
                    {copied ? 'Copied!' : 'Copy text'}
                </LemonButton>
            </div>
            <pre className="font-mono text-xs whitespace-pre-wrap p-4 bg-bg-light rounded border border-border overflow-auto max-h-[70vh]">
                {segments.map((segment, index) => {
                    if (segment.type === 'text') {
                        // Trim trailing whitespace if followed by gen_expandable
                        const nextSegment = segments[index + 1]
                        const content =
                            nextSegment?.type === 'gen_expandable' ? segment.content.trimEnd() : segment.content
                        return <span key={index}>{renderTextWithLinks(content, traceId)}</span>
                    }
                    if (segment.type === 'gen_expandable') {
                        const isExpanded = expandedSegments.has(index)
                        // Extract [GEN] or [SPAN] tag and rest of content
                        const tagMatch = segment.content.match(/^(\[(?:GEN|SPAN)\])\s*(.*)$/)
                        const tag = tagMatch ? tagMatch[1] : segment.content
                        const restContent = tagMatch ? tagMatch[2] : segment.content
                        return (
                            <span key={index}>
                                <Link
                                    to={urls.llmAnalyticsTrace(traceId!, { event: segment.eventId })}
                                    title="Jump to event"
                                >
                                    {tag}
                                </Link>
                                <button
                                    onClick={() => toggleSegment(index)}
                                    className="text-link hover:underline cursor-pointer"
                                    title={isExpanded ? 'Collapse' : 'Expand'}
                                >
                                    {isExpanded ? '[−]' : '[+]'}
                                </button>{' '}
                                {restContent.trim()}
                                {isExpanded && (
                                    <div className="ml-4 mt-2 mb-2 pl-4 border-l-2 border-border">
                                        <NestedContentRenderer
                                            content={segment.fullContent || ''}
                                            traceId={traceId}
                                            parentKey={`gen-${index}`}
                                            expandedSegments={expandedSegments}
                                            setExpandedSegments={setExpandedSegments}
                                            popoutSegment={popoutSegment}
                                            setPopoutSegment={setPopoutSegment}
                                        />
                                    </div>
                                )}
                            </span>
                        )
                    }
                    // Truncated segment
                    const isExpanded = expandedSegments.has(index)
                    const isPopoutOpen = popoutSegment === index
                    return (
                        <span key={index}>
                            {isExpanded ? (
                                <>
                                    {renderTextWithLinks(segment.fullContent || '', traceId)}
                                    <button
                                        onClick={() => toggleSegment(index)}
                                        className="text-link hover:underline cursor-pointer ml-1"
                                    >
                                        [collapse]
                                    </button>
                                </>
                            ) : (
                                <>
                                    <button
                                        onClick={() => toggleSegment(index)}
                                        className="text-link hover:underline cursor-pointer"
                                    >
                                        {segment.content}
                                    </button>
                                    <Tooltip
                                        title={
                                            isPopoutOpen ? (
                                                <div
                                                    data-popout-content
                                                    className="max-h-96 overflow-auto whitespace-pre-wrap font-mono text-xs"
                                                >
                                                    {segment.fullContent}
                                                </div>
                                            ) : null
                                        }
                                        containerClassName="max-w-4xl"
                                        placement="top"
                                        visible={isPopoutOpen}
                                    >
                                        <button
                                            data-popout-button
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                togglePopout(index)
                                            }}
                                            className="inline-flex items-center justify-center w-4 h-4 ml-1 text-muted hover:text-default transition-colors"
                                            title="Preview truncated content"
                                        >
                                            <IconExternal className="w-3 h-3" />
                                        </button>
                                    </Tooltip>
                                </>
                            )}
                        </span>
                    )
                })}
            </pre>
        </div>
    )
}
