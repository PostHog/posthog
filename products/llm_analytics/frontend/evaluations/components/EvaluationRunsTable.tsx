import { useActions, useValues } from 'kea'

import { IconCheck, IconChevronDown, IconMinus, IconRefresh, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonTable, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationPattern, EvaluationRun, EvaluationSummaryFilter } from '../types'

interface PatternCardProps {
    pattern: EvaluationPattern
    type: 'pass' | 'fail' | 'na'
    runsLookup: Record<string, EvaluationRun>
}

function PatternCard({ pattern, type, runsLookup }: PatternCardProps): JSX.Element {
    const borderClass = type === 'pass' ? 'border-success' : type === 'fail' ? 'border-danger' : 'border-muted'
    const iconClass = type === 'pass' ? 'text-success' : type === 'fail' ? 'text-danger' : 'text-muted'
    const Icon = type === 'pass' ? IconCheck : type === 'fail' ? IconX : IconMinus

    return (
        <div className={`border rounded-lg p-3 ${borderClass}`}>
            <div className="flex items-center gap-2 mb-2">
                <Icon className={iconClass} />
                <span className="font-semibold">{pattern.title}</span>
                <span className="text-xs text-muted bg-bg-light px-2 py-0.5 rounded">{pattern.frequency}</span>
            </div>
            <p className="text-sm text-default mb-2">{pattern.description}</p>
            <div className="text-xs text-muted bg-bg-light p-2 rounded">
                <strong>Example:</strong> {pattern.example_reasoning}
            </div>
            {pattern.example_generation_ids.length > 0 && (
                <div className="mt-2 flex items-center gap-2 flex-wrap">
                    <span className="text-xs text-muted">Examples:</span>
                    {pattern.example_generation_ids.map((genId) => {
                        const run = runsLookup[genId]
                        if (run) {
                            return (
                                <Link
                                    key={genId}
                                    to={urls.llmAnalyticsTrace(run.trace_id, { event: genId })}
                                    className="text-xs font-mono text-primary hover:underline"
                                >
                                    {genId.slice(0, 8)}...
                                </Link>
                            )
                        }
                        return (
                            <span key={genId} className="text-xs font-mono text-muted">
                                {genId.slice(0, 8)}...
                            </span>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

export function EvaluationRunsTable(): JSX.Element {
    const {
        evaluation,
        evaluationRuns,
        evaluationRunsLoading,
        runsSummary,
        evaluationSummary,
        evaluationSummaryLoading,
        evaluationSummaryFilter,
        summaryExpanded,
    } = useValues(llmEvaluationLogic)
    const { refreshEvaluationRuns, generateEvaluationSummary, setEvaluationSummaryFilter, toggleSummaryExpanded } =
        useActions(llmEvaluationLogic)
    const showSummaryFeature = useFeatureFlag('LLM_ANALYTICS_EVALUATIONS_SUMMARY')

    // Create a lookup map from generation_id to run for linking in pattern cards
    const runsLookup: Record<string, EvaluationRun> = {}
    for (const run of evaluationRuns) {
        runsLookup[run.generation_id] = run
    }

    const columns: LemonTableColumns<EvaluationRun> = [
        {
            title: 'Timestamp',
            key: 'timestamp',
            render: (_, run) => <TZLabel time={run.timestamp} />,
            sorter: (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        },
        {
            title: 'Generation ID',
            key: 'generation_id',
            render: (_, run) => (
                <div className="font-mono text-sm">
                    <Link
                        to={urls.llmAnalyticsTrace(run.trace_id, { event: run.generation_id })}
                        className="text-primary"
                    >
                        {run.generation_id.slice(0, 12)}...
                    </Link>
                </div>
            ),
        },
        {
            title: 'Result',
            key: 'result',
            render: (_, run) => {
                if (run.status === 'failed') {
                    return (
                        <LemonTag type="danger" icon={<IconWarning />}>
                            Error
                        </LemonTag>
                    )
                }
                if (run.status === 'running') {
                    return <LemonTag type="primary">Running...</LemonTag>
                }
                if (run.result === null) {
                    return (
                        <LemonTag type="muted" icon={<IconMinus />}>
                            N/A
                        </LemonTag>
                    )
                }
                return (
                    <div className="flex items-center gap-2">
                        {run.result ? (
                            <LemonTag type="success" icon={<IconCheck />}>
                                True
                            </LemonTag>
                        ) : (
                            <LemonTag type="danger" icon={<IconX />}>
                                False
                            </LemonTag>
                        )}
                    </div>
                )
            },
            sorter: (a, b) => {
                if (a.status !== 'completed' || b.status !== 'completed') {
                    return a.status.localeCompare(b.status)
                }
                const valA = a.result === null ? 0.5 : Number(a.result)
                const valB = b.result === null ? 0.5 : Number(b.result)
                return valB - valA
            },
        },
        {
            title: 'Reasoning',
            key: 'reasoning',
            render: (_, run) => (
                <Tooltip title={run.reasoning}>
                    <div className="max-w-md cursor-default">
                        <div className="text-sm text-default line-clamp-2">{run.reasoning}</div>
                    </div>
                </Tooltip>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, run) => {
                const statusMap = {
                    completed: { type: 'success' as const, text: 'Completed' },
                    failed: { type: 'danger' as const, text: 'Failed' },
                    running: { type: 'primary' as const, text: 'Running' },
                }
                const status = statusMap[run.status]
                return <LemonTag type={status.type}>{status.text}</LemonTag>
            },
        },
    ]

    const hasRuns = runsSummary && runsSummary.total > 0

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <div className="flex items-center gap-2">
                    {showSummaryFeature && hasRuns && (
                        <>
                            <LemonButton type="secondary" onClick={generateEvaluationSummary} size="small">
                                Summarize
                            </LemonButton>
                            <LemonSegmentedButton
                                value={evaluationSummaryFilter}
                                onChange={(value) => setEvaluationSummaryFilter(value as EvaluationSummaryFilter)}
                                options={[
                                    { value: 'all', label: 'All' },
                                    { value: 'pass', label: 'Passing' },
                                    { value: 'fail', label: 'Failing' },
                                    ...(evaluation?.output_config?.allows_na ? [{ value: 'na', label: 'N/A' }] : []),
                                ]}
                                size="small"
                            />
                        </>
                    )}
                </div>
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={refreshEvaluationRuns}
                    loading={evaluationRunsLoading}
                    size="small"
                >
                    Refresh
                </LemonButton>
            </div>

            {showSummaryFeature && evaluationSummaryLoading && (
                <div className="flex items-center justify-center py-6 border rounded-lg bg-bg-light">
                    <Spinner className="text-primary" />
                    <span className="ml-2 text-muted">Analyzing evaluation results...</span>
                </div>
            )}

            {showSummaryFeature && evaluationSummary && !evaluationSummaryLoading && (
                <div className="border rounded-lg bg-bg-light">
                    <button
                        className="w-full flex items-center justify-between p-3 hover:bg-border-light transition-colors cursor-pointer"
                        onClick={toggleSummaryExpanded}
                    >
                        <div className="text-left">
                            <span className="font-semibold text-sm">AI Summary</span>
                            <span className="text-xs text-muted ml-2">
                                {evaluationSummary.statistics.total_analyzed} runs analyzed
                            </span>
                        </div>
                        <IconChevronDown
                            className={`text-muted transition-transform ${summaryExpanded ? '' : '-rotate-90'}`}
                        />
                    </button>

                    {summaryExpanded && (
                        <div className="p-4 pt-0 space-y-4">
                            <div>
                                <p className="text-sm">{evaluationSummary.overall_assessment}</p>
                                <div className="mt-1 text-xs text-muted">
                                    {evaluationSummaryFilter === 'all' && (
                                        <>
                                            {evaluationSummary.statistics.pass_count} passed,{' '}
                                            {evaluationSummary.statistics.fail_count} failed
                                            {evaluationSummary.statistics.na_count > 0 && (
                                                <>, {evaluationSummary.statistics.na_count} N/A</>
                                            )}
                                        </>
                                    )}
                                    {evaluationSummaryFilter === 'pass' && (
                                        <>{evaluationSummary.statistics.pass_count} passing runs analyzed</>
                                    )}
                                    {evaluationSummaryFilter === 'fail' && (
                                        <>{evaluationSummary.statistics.fail_count} failing runs analyzed</>
                                    )}
                                    {evaluationSummaryFilter === 'na' && (
                                        <>{evaluationSummary.statistics.na_count} N/A runs analyzed</>
                                    )}
                                </div>
                            </div>

                            {evaluationSummaryFilter === 'all' && (
                                <div
                                    className={`grid gap-4 ${
                                        evaluationSummary.pass_patterns.length > 0 &&
                                        evaluationSummary.fail_patterns.length > 0
                                            ? 'grid-cols-2'
                                            : 'grid-cols-1'
                                    }`}
                                >
                                    {evaluationSummary.pass_patterns.length > 0 && (
                                        <div>
                                            <h4 className="font-semibold mb-2 flex items-center gap-2 text-sm">
                                                <IconCheck className="text-success" />
                                                Passing patterns
                                            </h4>
                                            <div className="space-y-2">
                                                {evaluationSummary.pass_patterns.map((pattern, i) => (
                                                    <PatternCard
                                                        key={i}
                                                        pattern={pattern}
                                                        type="pass"
                                                        runsLookup={runsLookup}
                                                    />
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {evaluationSummary.fail_patterns.length > 0 && (
                                        <div>
                                            <h4 className="font-semibold mb-2 flex items-center gap-2 text-sm">
                                                <IconX className="text-danger" />
                                                Failing patterns
                                            </h4>
                                            <div className="space-y-2">
                                                {evaluationSummary.fail_patterns.map((pattern, i) => (
                                                    <PatternCard
                                                        key={i}
                                                        pattern={pattern}
                                                        type="fail"
                                                        runsLookup={runsLookup}
                                                    />
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}

                            {evaluationSummaryFilter === 'pass' && (
                                <div>
                                    <h4 className="font-semibold mb-2 flex items-center gap-2 text-sm">
                                        <IconCheck className="text-success" />
                                        Passing patterns
                                    </h4>
                                    <div className="space-y-2">
                                        {evaluationSummary.pass_patterns.length > 0 ? (
                                            evaluationSummary.pass_patterns.map((pattern, i) => (
                                                <PatternCard
                                                    key={i}
                                                    pattern={pattern}
                                                    type="pass"
                                                    runsLookup={runsLookup}
                                                />
                                            ))
                                        ) : (
                                            <p className="text-sm text-muted">No passing patterns identified</p>
                                        )}
                                    </div>
                                </div>
                            )}

                            {evaluationSummaryFilter === 'fail' && (
                                <div>
                                    <h4 className="font-semibold mb-2 flex items-center gap-2 text-sm">
                                        <IconX className="text-danger" />
                                        Failing patterns
                                    </h4>
                                    <div className="space-y-2">
                                        {evaluationSummary.fail_patterns.length > 0 ? (
                                            evaluationSummary.fail_patterns.map((pattern, i) => (
                                                <PatternCard
                                                    key={i}
                                                    pattern={pattern}
                                                    type="fail"
                                                    runsLookup={runsLookup}
                                                />
                                            ))
                                        ) : (
                                            <p className="text-sm text-muted">No failing patterns identified</p>
                                        )}
                                    </div>
                                </div>
                            )}

                            {evaluationSummaryFilter === 'na' && (
                                <div>
                                    <h4 className="font-semibold mb-2 flex items-center gap-2 text-sm">
                                        <IconMinus className="text-muted" />
                                        N/A patterns
                                    </h4>
                                    <div className="space-y-2">
                                        {evaluationSummary.na_patterns.length > 0 ? (
                                            evaluationSummary.na_patterns.map((pattern, i) => (
                                                <PatternCard
                                                    key={i}
                                                    pattern={pattern}
                                                    type="na"
                                                    runsLookup={runsLookup}
                                                />
                                            ))
                                        ) : (
                                            <p className="text-sm text-muted">No N/A patterns identified</p>
                                        )}
                                    </div>
                                </div>
                            )}

                            {evaluationSummary.recommendations.length > 0 && (
                                <div>
                                    <h4 className="font-semibold mb-2 text-sm">Recommendations</h4>
                                    <ul className="list-disc list-inside space-y-1 text-sm">
                                        {evaluationSummary.recommendations.map((rec, i) => (
                                            <li key={i}>{rec}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            <LemonTable
                columns={columns}
                dataSource={evaluationRuns}
                loading={evaluationRunsLoading}
                rowKey="id"
                pagination={{
                    pageSize: 20,
                }}
                emptyState={
                    <div className="text-center py-8">
                        <div className="text-muted mb-2">No evaluation runs yet</div>
                        <div className="text-sm text-muted">
                            Runs will appear here once this evaluation starts executing based on your triggers.
                        </div>
                    </div>
                }
            />
        </div>
    )
}
