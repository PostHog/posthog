/**
 * Component for rendering text with clickable URLs, event links, and line numbers
 */
import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { TextPart, parseUrls } from '../parsing'
import { LineWithNumber } from './LineWithNumber'

interface TextWithLinksProps {
    text: string
    traceId?: string
    activeLineNumber?: number | null
    lineNumberPadding?: number
    onCopyPermalink?: (lineNumber: number) => void
    enableLineActions?: boolean
}

export function TextWithLinks({
    text,
    traceId,
    activeLineNumber,
    lineNumberPadding = 0,
    onCopyPermalink,
    enableLineActions = false,
}: TextWithLinksProps): JSX.Element {
    const parts = parseUrls(text, traceId)
    const result: JSX.Element[] = []

    parts.forEach((part, i) => {
        if (part.type === 'url') {
            result.push(
                <Link key={`url-${i}`} to={part.content} target="_blank" targetBlankIcon>
                    {part.content}
                </Link>
            )
        } else if (part.type === 'event_link' && traceId) {
            result.push(
                <Link key={`event-${i}`} to={urls.llmAnalyticsTrace(traceId, { event: part.eventId })}>
                    {part.displayText}
                </Link>
            )
        } else {
            // Must be TextPart - process line by line to handle line numbers
            const content = (part as TextPart).content
            const lines = content.split('\n')

            lines.forEach((line, lineIdx) => {
                if (lineIdx > 0) {
                    // Add newline between lines (except before first line)
                    result.push(<span key={`nl-${i}-${lineIdx}`}>{'\n'}</span>)
                }

                const lineMatch = line.match(/^(L\d+:)(.*)$/)
                if (lineMatch) {
                    const lineNumber = parseInt(lineMatch[1].slice(1, -1), 10)
                    const lineContent = lineMatch[2]
                    result.push(
                        <LineWithNumber
                            key={`line-${i}-${lineIdx}`}
                            lineNumber={lineNumber}
                            content={lineContent}
                            isActive={activeLineNumber === lineNumber}
                            padding={lineNumberPadding}
                            traceId={enableLineActions ? traceId : undefined}
                            onCopyPermalink={onCopyPermalink}
                        />
                    )
                } else {
                    result.push(<span key={`text-${i}-${lineIdx}`}>{line}</span>)
                }
            })
        }
    })

    return <>{result}</>
}
