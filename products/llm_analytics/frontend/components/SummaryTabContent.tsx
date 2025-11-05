/**
 * Summary Tab Content Component
 *
 * Provides AI-powered summarization of LLM traces and events with line references.
 */
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { LemonButton, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { StructuredSummary, summaryTabLogic } from './summaryTabLogic'

export interface SummaryTabContentProps {
    trace?: LLMTrace
    event?: LLMTraceEvent
    tree?: any[]
}

export function SummaryTabContent({ trace, event, tree }: SummaryTabContentProps): JSX.Element {
    const logic = summaryTabLogic({ trace, event, tree })
    const { summaryData, summaryDataLoading, summaryMode } = useValues(logic)
    const { generateSummary, setSummaryMode } = useActions(logic)

    const isSummarizable = trace || (event && (event.event === '$ai_generation' || event.event === '$ai_span'))

    if (!isSummarizable) {
        return <div className="p-4 text-muted">Summary is only available for traces, generations, and spans.</div>
    }

    // Get friendly event type name
    const getEventTypeName = (): string => {
        if (trace) {
            return 'trace'
        }
        if (event) {
            switch (event.event) {
                case '$ai_generation':
                    return 'generation'
                case '$ai_span':
                    return 'span'
                case '$ai_embedding':
                    return 'embedding'
                default:
                    return 'event'
            }
        }
        return 'event'
    }

    // Extract error message from loader failure if any
    const errorMessage = (logic.values as any).summaryDataFailure
        ? (logic.values as any).summaryDataFailure instanceof Error
            ? (logic.values as any).summaryDataFailure.message
            : typeof (logic.values as any).summaryDataFailure === 'string'
              ? (logic.values as any).summaryDataFailure
              : 'An unexpected error occurred'
        : null

    return (
        <div className="p-4 flex flex-col gap-4 h-full overflow-hidden">
            {!summaryData && !summaryDataLoading && !errorMessage && (
                <div className="flex flex-col items-center gap-4 py-8">
                    <div className="text-muted text-center">
                        <p>Generate an AI-powered summary of this {getEventTypeName()}.</p>
                    </div>
                    <div className="flex items-center gap-3">
                        <LemonSegmentedButton
                            value={summaryMode}
                            onChange={setSummaryMode}
                            options={[
                                {
                                    value: 'minimal',
                                    label: 'Minimal',
                                    tooltip: 'Quick 3-5 bullet point summary with key highlights',
                                },
                                {
                                    value: 'detailed',
                                    label: 'Detailed',
                                    tooltip: 'Comprehensive 5-10 point summary with full context',
                                },
                            ]}
                            size="small"
                        />
                        <LemonButton
                            type="primary"
                            onClick={() => generateSummary(summaryMode)}
                            data-attr="llm-analytics-generate-summary"
                        >
                            Generate Summary
                        </LemonButton>
                    </div>
                </div>
            )}

            {summaryDataLoading && (
                <div className="flex flex-col items-center gap-4 py-8">
                    <Spinner />
                    <div className="text-muted">Generating summary...</div>
                </div>
            )}

            {errorMessage && (
                <div className="bg-danger-highlight border border-danger rounded p-4">
                    <div className="font-semibold text-danger">Failed to generate summary</div>
                    <div className="text-sm mt-2">{errorMessage}</div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => generateSummary(summaryMode)}
                        className="mt-4"
                    >
                        Try Again
                    </LemonButton>
                </div>
            )}

            {summaryData && !summaryDataLoading && (
                <>
                    <div className="flex items-center gap-2 flex-none">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => generateSummary(summaryMode)}
                            data-attr="llm-analytics-regenerate-summary"
                        >
                            Regenerate
                        </LemonButton>
                        <LemonSegmentedButton
                            value={summaryMode}
                            onChange={setSummaryMode}
                            options={[
                                {
                                    value: 'minimal',
                                    label: 'Minimal',
                                    tooltip: 'Quick 3-5 bullet point summary with key highlights',
                                },
                                {
                                    value: 'detailed',
                                    label: 'Detailed',
                                    tooltip: 'Comprehensive 5-10 point summary with full context',
                                },
                            ]}
                            size="xsmall"
                        />
                    </div>

                    <div className="flex-none">
                        <div className="prose prose-sm max-w-none border rounded p-4 bg-bg-light overflow-x-auto">
                            <SummaryRenderer summary={summaryData.summary} />
                        </div>
                    </div>

                    <div className="flex-1 flex flex-col min-h-0">
                        <h4 className="font-semibold mb-2">Text Representation</h4>
                        <div className="border rounded flex-1 overflow-hidden">
                            <TextReprDisplay textRepr={summaryData.text_repr} trace={trace} event={event} />
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}

/**
 * Renders structured summary with collapsible sections
 */
function SummaryRenderer({ summary }: { summary: StructuredSummary }): JSX.Element {
    const [isFlowExpanded, setIsFlowExpanded] = useState(false)
    const [isSummaryExpanded, setIsSummaryExpanded] = useState(true)
    const [isNotesExpanded, setIsNotesExpanded] = useState(true)

    // Parse line references like L45, L45-52, L13-19, L553-555 and make them clickable
    const parseLineReferences = (text: string): (string | JSX.Element)[] => {
        const parts: (string | JSX.Element)[] = []
        // Match both bracketed [L10-20] and unbracketed L10-20 patterns
        // Also handles comma-separated ranges like [L13-19, L553-555] or L1940-1946, L2560-2581
        const regex = /\[L[\d\s,-]+\]|L\d+(?:-\d+)?(?:\s*,\s*L\d+(?:-\d+)?)*/g
        let lastIndex = 0
        let match

        while ((match = regex.exec(text)) !== null) {
            // Add text before the match
            if (match.index > lastIndex) {
                parts.push(text.slice(lastIndex, match.index))
            }

            const matchedText = match[0]
            // Extract all line numbers and ranges from the match
            let lineRangesText: string
            let displayText: string
            if (matchedText.startsWith('[')) {
                // Bracketed format: [L13-19, L553-555]
                lineRangesText = matchedText.slice(2, -1) // Remove [L and ]
                displayText = matchedText // Already has brackets
            } else {
                // Unbracketed format: L1386-1436, L1940-1946
                lineRangesText = matchedText.slice(1) // Remove leading L
                displayText = `[${matchedText}]` // Add brackets for display
            }

            // Parse individual ranges/lines (e.g., "13-19, 553-555" or "1386-1436, 1940-1946")
            const rangeStrings = lineRangesText.split(',').map((s) => s.trim())
            const lineRanges: Array<{ start: number; end: number }> = []

            for (const rangeStr of rangeStrings) {
                // Remove leading 'L' if present (for unbracketed format like "L1940-1946")
                const cleanedRange = rangeStr.replace(/^L/i, '')

                if (cleanedRange.includes('-')) {
                    const [start, end] = cleanedRange.split('-').map((s) => parseInt(s.trim()))
                    if (!isNaN(start) && !isNaN(end)) {
                        lineRanges.push({ start, end })
                    }
                } else {
                    const line = parseInt(cleanedRange)
                    if (!isNaN(line)) {
                        lineRanges.push({ start: line, end: line })
                    }
                }
            }

            parts.push(
                <button
                    key={match.index}
                    type="button"
                    className="text-link hover:underline font-semibold cursor-pointer"
                    onClick={(e) => {
                        e.preventDefault()

                        // Scroll to the first line in the first range
                        if (lineRanges.length > 0) {
                            const firstElement = document.getElementById(`summary-line-${lineRanges[0].start}`)
                            if (firstElement) {
                                firstElement.scrollIntoView({ behavior: 'smooth', block: 'center' })
                            }
                        }

                        // Highlight all lines in all ranges
                        for (const { start, end } of lineRanges) {
                            for (let i = start; i <= end; i++) {
                                const element = document.getElementById(`summary-line-${i}`)
                                if (element) {
                                    element.classList.add('bg-warning-highlight')
                                    element.classList.add('border-l-4')
                                    element.classList.add('border-warning')
                                }
                            }
                        }

                        // Remove highlight after 3 seconds
                        setTimeout(() => {
                            for (const { start, end } of lineRanges) {
                                for (let i = start; i <= end; i++) {
                                    const element = document.getElementById(`summary-line-${i}`)
                                    if (element) {
                                        element.classList.remove('bg-warning-highlight')
                                        element.classList.remove('border-l-4')
                                        element.classList.remove('border-warning')
                                    }
                                }
                            }
                        }, 3000)
                    }}
                >
                    {displayText}
                </button>
            )

            lastIndex = regex.lastIndex
        }

        // Add remaining text
        if (lastIndex < text.length) {
            parts.push(text.slice(lastIndex))
        }

        return parts
    }

    const renderLineRefs = (lineRefs: string): JSX.Element | null => {
        if (!lineRefs || lineRefs.trim() === '') {
            return null
        }
        return <span className="ml-2">{parseLineReferences(lineRefs)}</span>
    }

    return (
        <div className="space-y-4">
            {/* Flow Diagram - Collapsible ASCII */}
            <div className="border border-border rounded">
                <Tooltip title="ASCII diagram showing the main steps and flow of execution">
                    <button
                        type="button"
                        className="w-full text-left px-3 py-2 font-medium flex items-center gap-2 hover:bg-accent text-sm"
                        onClick={() => setIsFlowExpanded(!isFlowExpanded)}
                    >
                        <span className="text-xs">{isFlowExpanded ? '▼' : '▶'}</span>
                        Flow Diagram
                    </button>
                </Tooltip>
                {isFlowExpanded && (
                    <div className="px-3 py-2 border-t border-border bg-bg-light">
                        <pre className="font-mono text-sm whitespace-pre overflow-x-auto m-0">
                            {summary.flow_diagram}
                        </pre>
                    </div>
                )}
            </div>

            {/* Summary Bullets - Collapsible */}
            <div className="border border-border rounded">
                <Tooltip title="Key highlights and main actions from this trace or event">
                    <button
                        type="button"
                        className="w-full text-left px-3 py-2 font-medium flex items-center gap-2 hover:bg-accent text-sm"
                        onClick={() => setIsSummaryExpanded(!isSummaryExpanded)}
                    >
                        <span className="text-xs">{isSummaryExpanded ? '▼' : '▶'}</span>
                        Summary Points
                    </button>
                </Tooltip>
                {isSummaryExpanded && (
                    <div className="px-3 py-2 border-t border-border bg-bg-light">
                        <ul className="list-disc list-inside space-y-1">
                            {summary.summary_bullets.map((bullet, idx) => (
                                <li key={idx} className="text-sm">
                                    {bullet.text}
                                    {renderLineRefs(bullet.line_refs)}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>

            {/* Interesting Notes - Collapsible (if present) */}
            {summary.interesting_notes.length > 0 && (
                <div className="border border-border rounded">
                    <Tooltip title="Notable observations like errors, unusual patterns, or important details">
                        <button
                            type="button"
                            className="w-full text-left px-3 py-2 font-medium flex items-center gap-2 hover:bg-accent text-sm"
                            onClick={() => setIsNotesExpanded(!isNotesExpanded)}
                        >
                            <span className="text-xs">{isNotesExpanded ? '▼' : '▶'}</span>
                            Interesting Notes
                        </button>
                    </Tooltip>
                    {isNotesExpanded && (
                        <div className="px-3 py-2 border-t border-border bg-bg-light">
                            <ul className="list-disc list-inside space-y-1">
                                {summary.interesting_notes.map((note, idx) => (
                                    <li key={idx} className="text-sm">
                                        {note.text}
                                        {renderLineRefs(note.line_refs)}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

/**
 * Displays line-numbered text representation with clickable line numbers
 * that link to the Conversation tab's text view
 */
function TextReprDisplay({ textRepr, event }: { textRepr: string; event?: LLMTraceEvent }): JSX.Element {
    // Parse text repr to add line anchors
    const lines = textRepr.split('\n')

    const handleLineClick = (lineNumber: number): void => {
        // Update URL with line parameter
        const url = new URL(window.location.href)
        url.searchParams.set('line', lineNumber.toString())

        // If we're viewing a specific event's summary, ensure the URL includes that event ID
        // This prevents defaulting to the top-level trace
        if (event) {
            // Update the path to include the event ID
            const pathParts = url.pathname.split('/')
            const traceIndex = pathParts.findIndex((part) => part === 'traces')
            if (traceIndex !== -1 && traceIndex + 1 < pathParts.length) {
                // Replace or add the event ID after the trace ID
                pathParts[traceIndex + 1] = event.id
                url.pathname = pathParts.join('/')
            }
        }

        const fullUrl = url.toString()

        // Copy URL to clipboard
        void copyToClipboard(fullUrl, 'line reference URL')

        // Navigate to the URL, which will be picked up by the Conversation tab's text view
        router.actions.push(url.pathname + url.search)

        // Note: User will need to manually switch to Conversation tab and TextView mode
        // to see the highlighted line. We don't auto-switch to avoid disrupting workflow.
        lemonToast.info('Line reference URL copied. Switch to Conversation → Text view to see highlighted line.')
    }

    return (
        <div className="p-4 overflow-auto h-full font-mono text-xs whitespace-pre bg-bg-light">
            {lines.map((line, index) => {
                // Extract line number from zero-padded format "L001:", "L010:", "L100:"
                const match = line.match(/^(L\d+:)(.*)$/)
                // Parse to int to remove leading zeros so ID matches what click handlers expect
                const lineNumber = match ? parseInt(match[1].slice(1, -1), 10) : null
                const linePrefix = match ? match[1] : ''
                const lineContent = match ? match[2] : line

                return (
                    <div
                        key={index}
                        id={lineNumber ? `summary-line-${lineNumber}` : undefined}
                        className="transition-all duration-300 ease-in-out"
                    >
                        {linePrefix && lineNumber ? (
                            <Tooltip title="Click to link to this line in Conversation text view">
                                <button
                                    type="button"
                                    className="text-muted hover:text-link cursor-pointer"
                                    onClick={() => handleLineClick(lineNumber)}
                                >
                                    {linePrefix}
                                </button>
                            </Tooltip>
                        ) : (
                            linePrefix && <span className="text-muted">{linePrefix}</span>
                        )}
                        {lineContent}
                    </div>
                )
            })}
        </div>
    )
}
