/**
 * Summary Tab Content Component
 *
 * Provides AI-powered summarization of LLM traces and events with line references.
 */
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconMarkdown, IconMarkdownFilled } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { SummaryMode, summaryTabLogic } from './summaryTabLogic'

export interface SummaryTabContentProps {
    trace?: LLMTrace
    event?: LLMTraceEvent
    tree?: any[]
}

export function SummaryTabContent({ trace, event, tree }: SummaryTabContentProps): JSX.Element {
    const logic = summaryTabLogic({ trace, event, tree })
    const { summaryData, summaryDataLoading } = useValues(logic)
    const { generateSummary } = useActions(logic)
    const [isRenderingMarkdown, setIsRenderingMarkdown] = useState(true)
    const [summaryMode, setSummaryMode] = useState<SummaryMode>('detailed')

    const isSummarizable = trace || (event && (event.event === '$ai_generation' || event.event === '$ai_span'))

    if (!isSummarizable) {
        return <div className="p-4 text-muted">Summary is only available for traces, generations, and spans.</div>
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
                    <div className="relative group flex-none">
                        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 z-10 bg-bg-light p-1 rounded shadow-md">
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
                            <LemonButton
                                size="small"
                                noPadding
                                icon={isRenderingMarkdown ? <IconMarkdownFilled /> : <IconMarkdown />}
                                tooltip="Toggle markdown rendering"
                                onClick={() => setIsRenderingMarkdown(!isRenderingMarkdown)}
                            />
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => generateSummary(summaryMode)}
                                data-attr="llm-analytics-regenerate-summary"
                            >
                                Regenerate
                            </LemonButton>
                        </div>
                        <div className="prose prose-sm max-w-none border rounded p-4 bg-bg-light overflow-x-auto">
                            <SummaryRenderer summary={summaryData.summary} isRenderingMarkdown={isRenderingMarkdown} />
                        </div>
                    </div>

                    <div className="flex-1 flex flex-col min-h-0">
                        <h4 className="font-semibold mb-2">Text Representation</h4>
                        <div className="border rounded flex-1 overflow-hidden">
                            <TextReprDisplay textRepr={summaryData.text_repr} />
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}

/**
 * Renders summary text with interactive line references
 */
function SummaryRenderer({
    summary,
    isRenderingMarkdown,
}: {
    summary: string
    isRenderingMarkdown: boolean
}): JSX.Element {
    // Parse line references like [L45], [L45-52], [L13-19, L553-555], L1386-1436, or L2560-2581 and make them clickable
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

            const displayText = match[0]
            // Extract all line numbers and ranges from the match
            let lineRangesText: string
            if (displayText.startsWith('[')) {
                // Bracketed format: [L13-19, L553-555]
                lineRangesText = displayText.slice(2, -1) // Remove [L and ]
            } else {
                // Unbracketed format: L1386-1436, L1940-1946
                lineRangesText = displayText.slice(1) // Remove leading L
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
                            const firstElement = document.getElementById(`line-${lineRanges[0].start}`)
                            if (firstElement) {
                                firstElement.scrollIntoView({ behavior: 'smooth', block: 'center' })
                            }
                        }

                        // Highlight all lines in all ranges
                        for (const { start, end } of lineRanges) {
                            for (let i = start; i <= end; i++) {
                                const element = document.getElementById(`line-${i}`)
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
                                    const element = document.getElementById(`line-${i}`)
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

    if (isRenderingMarkdown) {
        // For markdown mode, render as-is without processing line references
        // This preserves markdown structure (line references visible but not interactive)
        return (
            <div>
                <LemonMarkdown>{summary}</LemonMarkdown>
            </div>
        )
    }

    // For plain text mode, process and display
    const processedSummary = parseLineReferences(summary)
    return (
        <div className="whitespace-pre font-mono">
            {processedSummary.map((part, index) => (typeof part === 'string' ? part : <span key={index}>{part}</span>))}
        </div>
    )
}

/**
 * Displays line-numbered text representation with anchor navigation
 */
function TextReprDisplay({ textRepr }: { textRepr: string }): JSX.Element {
    // Parse text repr to add line anchors
    const lines = textRepr.split('\n')

    return (
        <div className="p-4 overflow-auto h-full font-mono text-sm whitespace-pre bg-bg-light">
            {lines.map((line, index) => {
                // Extract line number from zero-padded format "L001:", "L010:", "L100:"
                const match = line.match(/^L(\d+):/)
                const lineNumber = match ? match[1] : null

                return (
                    <div
                        key={index}
                        id={lineNumber ? `line-${lineNumber}` : undefined}
                        className="hover:bg-accent transition-all duration-300 ease-in-out"
                    >
                        {line}
                    </div>
                )
            })}
        </div>
    )
}
