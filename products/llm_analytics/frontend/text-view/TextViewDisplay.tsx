/**
 * Text view display component for generation events
 * Shows a formatted text representation with copy functionality and expandable truncated sections
 */
import { useEffect, useState } from 'react'

import { IconCopy, IconExternal } from '@posthog/icons'
import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { formatGenerationTextRepr } from './textFormatter'

interface TextSegment {
    type: 'text' | 'truncated'
    content: string
    fullContent?: string
    charCount?: number
}

/**
 * Parse text to find truncation markers and split into segments
 */
function parseTextSegments(text: string): TextSegment[] {
    const segments: TextSegment[] = []
    const markerRegex = /<<<TRUNCATED\|([^|]+)\|(\d+)>>>/g

    let lastIndex = 0
    let match: RegExpExecArray | null

    while ((match = markerRegex.exec(text)) !== null) {
        // Add text before the marker
        if (match.index > lastIndex) {
            segments.push({
                type: 'text',
                content: text.slice(lastIndex, match.index),
            })
        }

        // Add truncated segment
        const encodedContent = match[1]
        const charCount = parseInt(match[2], 10)
        try {
            const fullContent = decodeURIComponent(atob(encodedContent))
            segments.push({
                type: 'truncated',
                content: `... (${charCount} chars truncated)`,
                fullContent,
                charCount,
            })
        } catch {
            // If decoding fails, show as regular text
            segments.push({
                type: 'text',
                content: match[0],
            })
        }

        lastIndex = match.index + match[0].length
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

/**
 * Parse text to find URLs and split into text/URL parts
 */
function parseUrls(text: string): TextPart[] {
    const parts: TextPart[] = []
    // Match URLs (http, https, ftp protocols)
    const urlRegex = /(https?:\/\/[^\s]+)/g
    let lastIndex = 0
    let match: RegExpExecArray | null

    while ((match = urlRegex.exec(text)) !== null) {
        // Add text before the URL
        if (match.index > lastIndex) {
            parts.push({
                type: 'text',
                content: text.slice(lastIndex, match.index),
            })
        }

        // Add URL
        parts.push({
            type: 'url',
            content: match[0],
        })

        lastIndex = match.index + match[0].length
    }

    // Add remaining text
    if (lastIndex < text.length) {
        parts.push({
            type: 'text',
            content: text.slice(lastIndex),
        })
    }

    // If no URLs found, return the whole text as one part
    if (parts.length === 0) {
        parts.push({
            type: 'text',
            content: text,
        })
    }

    return parts
}

/**
 * Render text with clickable URLs
 */
function renderTextWithLinks(text: string): JSX.Element[] {
    const parts = parseUrls(text)
    return parts.map((part, i) => {
        if (part.type === 'url') {
            return (
                <Link key={i} to={part.content} target="_blank" targetBlankIcon>
                    {part.content}
                </Link>
            )
        }
        return <span key={i}>{part.content}</span>
    })
}

export function TextViewDisplay({ event }: { event: LLMTraceEvent }): JSX.Element {
    const [copied, setCopied] = useState(false)
    const textRepr = formatGenerationTextRepr(event)
    const segments = parseTextSegments(textRepr)
    const [expandedSegments, setExpandedSegments] = useState<Set<number>>(new Set())
    const [popoutSegment, setPopoutSegment] = useState<number | null>(null)

    // Get indices of all truncated segments
    const truncatedIndices = segments
        .map((seg, idx) => (seg.type === 'truncated' ? idx : -1))
        .filter((idx) => idx !== -1)

    const allExpanded = truncatedIndices.length > 0 && truncatedIndices.every((idx) => expandedSegments.has(idx))

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
            // Expand all
            setExpandedSegments(new Set(truncatedIndices))
        }
    }

    const togglePopout = (index: number): void => {
        setPopoutSegment((prev) => (prev === index ? null : index))
    }

    return (
        <div className="relative">
            <div className="absolute top-2 right-2 z-10 flex gap-2">
                {truncatedIndices.length > 0 && (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={toggleExpandAll}
                        tooltip={allExpanded ? 'Collapse all truncated sections' : 'Expand all truncated sections'}
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
                        return <span key={index}>{renderTextWithLinks(segment.content)}</span>
                    }
                    const isExpanded = expandedSegments.has(index)
                    const isPopoutOpen = popoutSegment === index
                    return (
                        <span key={index}>
                            {isExpanded ? (
                                <>
                                    {renderTextWithLinks(segment.fullContent || '')}
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
                                                    className="max-w-2xl max-h-96 overflow-auto whitespace-pre-wrap font-mono text-xs p-2"
                                                >
                                                    {segment.fullContent}
                                                </div>
                                            ) : null
                                        }
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
