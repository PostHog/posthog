import { useActions, useValues } from 'kea'

import { IconBolt, IconCheck, IconX } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationPattern, EvaluationSummaryFilter } from '../types'

interface PatternCardProps {
    pattern: EvaluationPattern
    type: 'pass' | 'fail'
}

function PatternCard({ pattern, type }: PatternCardProps): JSX.Element {
    return (
        <div className={`border rounded-lg p-3 ${type === 'pass' ? 'border-success' : 'border-danger'}`}>
            <div className="flex items-center gap-2 mb-2">
                {type === 'pass' ? <IconCheck className="text-success" /> : <IconX className="text-danger" />}
                <span className="font-semibold">{pattern.title}</span>
                <span className="text-xs text-muted bg-bg-light px-2 py-0.5 rounded">{pattern.frequency}</span>
            </div>
            <p className="text-sm text-default mb-2">{pattern.description}</p>
            <div className="text-xs text-muted bg-bg-light p-2 rounded">
                <strong>Example:</strong> {pattern.example_reasoning}
            </div>
        </div>
    )
}

export function EvaluationSummaryModal(): JSX.Element {
    const { summaryModalOpen, evaluationSummary, evaluationSummaryLoading, evaluationSummaryFilter, runsSummary } =
        useValues(llmEvaluationLogic)
    const { closeSummaryModal, setEvaluationSummaryFilter, generateEvaluationSummary } = useActions(llmEvaluationLogic)

    const hasRuns = runsSummary && runsSummary.total > 0

    return (
        <LemonModal
            isOpen={summaryModalOpen}
            onClose={closeSummaryModal}
            title="Evaluation results summary"
            description="AI-powered analysis of patterns in your evaluation results"
            width={700}
        >
            <div className="space-y-4">
                <div className="flex items-center gap-4">
                    <span className="text-sm font-medium">Summarize:</span>
                    <LemonSegmentedButton
                        value={evaluationSummaryFilter}
                        onChange={(value) => setEvaluationSummaryFilter(value as EvaluationSummaryFilter)}
                        options={[
                            { value: 'all', label: 'All results' },
                            { value: 'pass', label: 'Passing only' },
                            { value: 'fail', label: 'Failing only' },
                        ]}
                        size="small"
                    />
                    <LemonButton
                        type="primary"
                        icon={<IconBolt />}
                        onClick={generateEvaluationSummary}
                        loading={evaluationSummaryLoading}
                        disabledReason={!hasRuns ? 'No evaluation runs to summarize' : undefined}
                        size="small"
                    >
                        Generate summary
                    </LemonButton>
                </div>

                {evaluationSummaryLoading && (
                    <div className="flex items-center justify-center py-8">
                        <Spinner className="text-primary" />
                        <span className="ml-2">Analyzing evaluation results...</span>
                    </div>
                )}

                {evaluationSummary && !evaluationSummaryLoading && (
                    <div className="space-y-6">
                        <div className="bg-bg-light p-4 rounded-lg">
                            <h4 className="font-semibold mb-2">Overall assessment</h4>
                            <p className="text-sm">{evaluationSummary.overall_assessment}</p>
                            <div className="mt-2 text-xs text-muted">
                                Analyzed {evaluationSummary.statistics.total_analyzed} runs:{' '}
                                {evaluationSummary.statistics.pass_count} passed,{' '}
                                {evaluationSummary.statistics.fail_count} failed
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <h4 className="font-semibold mb-3 flex items-center gap-2">
                                    <IconCheck className="text-success" />
                                    Passing patterns
                                </h4>
                                <div className="space-y-3">
                                    {evaluationSummary.pass_patterns.length > 0 ? (
                                        evaluationSummary.pass_patterns.map((pattern, i) => (
                                            <PatternCard key={i} pattern={pattern} type="pass" />
                                        ))
                                    ) : (
                                        <p className="text-sm text-muted">No passing patterns identified</p>
                                    )}
                                </div>
                            </div>

                            <div>
                                <h4 className="font-semibold mb-3 flex items-center gap-2">
                                    <IconX className="text-danger" />
                                    Failing patterns
                                </h4>
                                <div className="space-y-3">
                                    {evaluationSummary.fail_patterns.length > 0 ? (
                                        evaluationSummary.fail_patterns.map((pattern, i) => (
                                            <PatternCard key={i} pattern={pattern} type="fail" />
                                        ))
                                    ) : (
                                        <p className="text-sm text-muted">No failing patterns identified</p>
                                    )}
                                </div>
                            </div>
                        </div>

                        {evaluationSummary.recommendations.length > 0 && (
                            <div>
                                <h4 className="font-semibold mb-3">Recommendations</h4>
                                <ul className="list-disc list-inside space-y-1 text-sm">
                                    {evaluationSummary.recommendations.map((rec, i) => (
                                        <li key={i}>{rec}</li>
                                    ))}
                                </ul>
                            </div>
                        )}
                    </div>
                )}

                {!evaluationSummary && !evaluationSummaryLoading && (
                    <div className="text-center py-8 text-muted">
                        <p>Click "Generate summary" to analyze your evaluation results</p>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
