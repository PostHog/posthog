/**
 * Summary Tab Content Component
 *
 * Provides AI-powered summarization of LLM traces and events with line references.
 */
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconMarkdown, IconMarkdownFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { summaryTabLogic } from './summaryTabLogic'

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
        <div className="p-4 space-y-4">
            {!summaryData && !summaryDataLoading && !errorMessage && (
                <div className="flex flex-col items-center gap-4 py-8">
                    <div className="text-muted text-center">
                        <p>Generate an AI-powered summary of this {trace ? 'trace' : 'event'}.</p>
                        <p className="text-sm mt-2">
                            The summary will include key insights and line references to the text representation.
                        </p>
                    </div>
                    <LemonButton type="primary" onClick={generateSummary} data-attr="llm-analytics-generate-summary">
                        Generate Summary
                    </LemonButton>
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
                    <LemonButton type="secondary" size="small" onClick={generateSummary} className="mt-4">
                        Try Again
                    </LemonButton>
                </div>
            )}

            {summaryData && !summaryDataLoading && (
                <>
                    <div className="relative group">
                        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 z-10 bg-bg-light p-1 rounded shadow-md">
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
                                onClick={generateSummary}
                                data-attr="llm-analytics-regenerate-summary"
                            >
                                Regenerate
                            </LemonButton>
                        </div>
                        <div className="prose prose-sm max-w-none border rounded p-4 bg-bg-light">
                            <SummaryRenderer summary={summaryData.summary} isRenderingMarkdown={isRenderingMarkdown} />
                        </div>
                    </div>

                    <div>
                        <h4 className="font-semibold mb-2">Text Representation</h4>
                        <div className="border rounded">
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
    // Parse line references like [L45] or [L45-52] and make them clickable
    const parseLineReferences = (text: string): (string | JSX.Element)[] => {
        const parts: (string | JSX.Element)[] = []
        const regex = /\[L(\d+)(?:-(\d+))?\]/g
        let lastIndex = 0
        let match

        while ((match = regex.exec(text)) !== null) {
            // Add text before the match
            if (match.index > lastIndex) {
                parts.push(text.slice(lastIndex, match.index))
            }

            // Add clickable line reference
            const startLine = match[1]
            const endLine = match[2]
            const displayText = endLine ? `[L${startLine}-${endLine}]` : `[L${startLine}]`

            parts.push(
                <button
                    key={match.index}
                    type="button"
                    className="text-link hover:underline font-semibold cursor-pointer"
                    onClick={(e) => {
                        e.preventDefault()
                        const element = document.getElementById(`line-${startLine}`)
                        if (element) {
                            element.scrollIntoView({ behavior: 'smooth', block: 'center' })
                            // Briefly highlight the line
                            element.classList.add('bg-primary-highlight')
                            setTimeout(() => element.classList.remove('bg-primary-highlight'), 2000)
                        }
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
        // For markdown mode, we need to process the text before rendering
        const processedSummary = parseLineReferences(summary)
        return (
            <div className="whitespace-pre-wrap">
                {processedSummary.map((part, index) => {
                    if (typeof part === 'string') {
                        return <LemonMarkdown key={index}>{part}</LemonMarkdown>
                    }
                    return part
                })}
            </div>
        )
    }

    // For plain text mode, process and display
    const processedSummary = parseLineReferences(summary)
    return (
        <div className="whitespace-pre-wrap font-mono">
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
        <div className="p-4 overflow-auto max-h-96 font-mono text-sm whitespace-pre bg-bg-light">
            {lines.map((line, index) => {
                // Extract line number from format "L  1:", "L 10:", "L100:"
                const match = line.match(/^L\s*(\d+):/)
                const lineNumber = match ? match[1] : null

                return (
                    <div
                        key={index}
                        id={lineNumber ? `line-${lineNumber}` : undefined}
                        className="hover:bg-accent transition-colors"
                    >
                        {line}
                    </div>
                )
            })}
        </div>
    )
}
