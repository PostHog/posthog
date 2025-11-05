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

import { LLMTrace, LLMTraceEvent } from '../types'
import { summaryTabLogic } from './summaryTabLogic'

export interface SummaryTabContentProps {
    trace?: LLMTrace
    event?: LLMTraceEvent
    tree?: any[]
}

export function SummaryTabContent({ trace, event, tree }: SummaryTabContentProps): JSX.Element {
    const logic = summaryTabLogic({ trace, event, tree })
    const { summary, summaryLoading, summaryError } = useValues(logic)
    const { generateSummary } = useActions(logic)
    const [isRenderingMarkdown, setIsRenderingMarkdown] = useState(true)

    const isSummarizable = trace || (event && (event.event === '$ai_generation' || event.event === '$ai_span'))

    if (!isSummarizable) {
        return <div className="p-4 text-muted">Summary is only available for traces, generations, and spans.</div>
    }

    return (
        <div className="p-4 space-y-4">
            {!summary && !summaryLoading && !summaryError && (
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

            {summaryLoading && (
                <div className="flex flex-col items-center gap-4 py-8">
                    <Spinner />
                    <div className="text-muted">Generating summary...</div>
                </div>
            )}

            {summaryError && (
                <div className="bg-danger-highlight border border-danger rounded p-4">
                    <div className="font-semibold text-danger">Failed to generate summary</div>
                    <div className="text-sm mt-2">{summaryError}</div>
                    <LemonButton type="secondary" size="small" onClick={generateSummary} className="mt-4">
                        Try Again
                    </LemonButton>
                </div>
            )}

            {summary && !summaryLoading && (
                <div>
                    <div className="flex justify-end items-center gap-1 mb-4">
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
                    <div className="prose prose-sm max-w-none">
                        <SummaryRenderer summary={summary} isRenderingMarkdown={isRenderingMarkdown} />
                    </div>
                </div>
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
    // TODO: Parse line references like [L45] or [L45-52] and make them clickable with tooltips

    if (isRenderingMarkdown) {
        return <LemonMarkdown className="whitespace-pre-wrap">{summary}</LemonMarkdown>
    }

    return <div className="whitespace-pre-wrap font-mono">{summary}</div>
}
