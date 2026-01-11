/**
 * Summary View Display Component
 *
 * Provides AI-powered summarization of LLM traces and events with line references.
 */
import { useActions, useValues } from 'kea'

import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { EnrichedTraceTreeNode } from '../llmAnalyticsTraceDataLogic'
import { SummaryRenderer } from './components/SummaryRenderer'
import { TextReprDisplay } from './components/TextReprDisplay'
import { summaryViewLogic } from './summaryViewLogic'

export interface SummaryViewDisplayProps {
    trace?: LLMTrace
    event?: LLMTraceEvent
    tree?: EnrichedTraceTreeNode[]
    autoGenerate?: boolean
}

interface SummaryViewLogicValues {
    summaryData: { summary: any; text_repr: string } | null
    summaryDataLoading: boolean
    summaryMode: 'minimal' | 'detailed'
    summaryDataFailure?: Error | string | unknown
}

export function SummaryViewDisplay({ trace, event, tree, autoGenerate }: SummaryViewDisplayProps): JSX.Element {
    const logic = summaryViewLogic({ trace, event, tree, autoGenerate })
    const { summaryData, summaryDataLoading, summaryMode, feedbackGiven } = useValues(logic)
    const { generateSummary, setSummaryMode, regenerateSummary, reportFeedback } = useActions(logic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    // Compute derived values from props
    const isSummarizable = !!trace || !!(event && (event.event === '$ai_generation' || event.event === '$ai_span'))

    const eventTypeName = (() => {
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
    })()

    if (!isSummarizable) {
        return <div className="p-4 text-muted">Summary is only available for traces, generations, and spans.</div>
    }

    // Extract error message from loader failure if any
    const logicValues = logic.values as SummaryViewLogicValues
    const errorMessage = logicValues.summaryDataFailure
        ? logicValues.summaryDataFailure instanceof Error
            ? logicValues.summaryDataFailure.message
            : typeof logicValues.summaryDataFailure === 'string'
              ? logicValues.summaryDataFailure
              : 'An unexpected error occurred'
        : null

    return (
        <div className="p-4 flex flex-col gap-4 h-full overflow-hidden">
            {!summaryData && !summaryDataLoading && !errorMessage && (
                <div className="flex flex-col items-center gap-4 py-8">
                    <div className="text-muted text-center">
                        <p>Generate an AI-powered summary of this {eventTypeName}.</p>
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
                            data-attr="summary-mode-selector"
                        />
                        {!dataProcessingAccepted ? (
                            <AIConsentPopoverWrapper
                                showArrow
                                onApprove={() => generateSummary({ mode: summaryMode })}
                                hidden={summaryDataLoading}
                            >
                                <LemonButton
                                    type="primary"
                                    data-attr="llm-analytics-generate-summary"
                                    loading={summaryDataLoading}
                                    disabledReason="AI data processing must be approved to generate summaries"
                                >
                                    Generate Summary
                                </LemonButton>
                            </AIConsentPopoverWrapper>
                        ) : (
                            <LemonButton
                                type="primary"
                                onClick={() => generateSummary({ mode: summaryMode })}
                                data-attr="llm-analytics-generate-summary"
                                loading={summaryDataLoading}
                            >
                                Generate Summary
                            </LemonButton>
                        )}
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
                    {!dataProcessingAccepted ? (
                        <AIConsentPopoverWrapper
                            showArrow
                            onApprove={() => generateSummary({ mode: summaryMode })}
                            hidden={summaryDataLoading}
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                className="mt-4"
                                loading={summaryDataLoading}
                                disabledReason="AI data processing must be approved to generate summaries"
                            >
                                Try Again
                            </LemonButton>
                        </AIConsentPopoverWrapper>
                    ) : (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => generateSummary({ mode: summaryMode })}
                            className="mt-4"
                            loading={summaryDataLoading}
                        >
                            Try Again
                        </LemonButton>
                    )}
                </div>
            )}

            {summaryData && !summaryDataLoading && (
                <>
                    <div className="flex items-center gap-2 flex-none">
                        {!dataProcessingAccepted ? (
                            <AIConsentPopoverWrapper
                                showArrow
                                onApprove={() => regenerateSummary()}
                                hidden={summaryDataLoading}
                            >
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    data-attr="llm-analytics-regenerate-summary"
                                    loading={summaryDataLoading}
                                    disabledReason="AI data processing must be approved to generate summaries"
                                >
                                    Regenerate
                                </LemonButton>
                            </AIConsentPopoverWrapper>
                        ) : (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => regenerateSummary()}
                                data-attr="llm-analytics-regenerate-summary"
                                loading={summaryDataLoading}
                            >
                                Regenerate
                            </LemonButton>
                        )}
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
                            data-attr="summary-mode-selector"
                        />
                    </div>

                    <div className="flex-none">
                        <div className="prose prose-sm max-w-none border rounded p-4 bg-bg-light overflow-x-auto">
                            <SummaryRenderer
                                summary={summaryData.summary}
                                trace={trace}
                                event={event}
                                tree={tree}
                                headerActions={
                                    <div className="flex gap-1 items-center not-prose">
                                        <span className="text-muted text-xs mr-1">
                                            {feedbackGiven !== null ? 'Thanks!' : 'Helpful?'}
                                        </span>
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconThumbsUp />}
                                            onClick={() => reportFeedback(true)}
                                            tooltip="Helpful"
                                            disabled={feedbackGiven !== null}
                                            active={feedbackGiven === true}
                                            data-attr="llma-summary-feedback-positive"
                                        />
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconThumbsDown />}
                                            onClick={() => reportFeedback(false)}
                                            tooltip="Not helpful"
                                            disabled={feedbackGiven !== null}
                                            active={feedbackGiven === false}
                                            data-attr="llma-summary-feedback-negative"
                                        />
                                    </div>
                                }
                            />
                        </div>
                    </div>

                    <div className="flex flex-col min-h-0 max-h-[800px]">
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
