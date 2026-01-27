import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCheck, IconChevronDown, IconMinus, IconX } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationPattern, EvaluationRun, EvaluationSummary, EvaluationSummaryFilter } from '../types'
import { PatternCard } from './PatternCard'

export function EvaluationSummaryControls(): JSX.Element | null {
    const {
        evaluation,
        runsSummary,
        runsToSummarizeCount,
        evaluationSummary,
        evaluationSummaryLoading,
        evaluationSummaryFilter,
    } = useValues(llmEvaluationLogic)
    const { generateEvaluationSummary, regenerateEvaluationSummary, setEvaluationSummaryFilter } =
        useActions(llmEvaluationLogic)
    const showSummaryFeature = useFeatureFlag('LLM_ANALYTICS_EVALUATIONS_SUMMARY')

    if (!showSummaryFeature || !runsSummary || runsSummary.total === 0) {
        return null
    }

    return (
        <div className="flex items-center gap-2">
            <Tooltip
                title={
                    runsToSummarizeCount === 0
                        ? 'No runs match the current filter'
                        : evaluationSummary
                          ? `Regenerate AI summary for ${runsToSummarizeCount} ${
                                evaluationSummaryFilter === 'all'
                                    ? ''
                                    : evaluationSummaryFilter === 'pass'
                                      ? 'passing '
                                      : evaluationSummaryFilter === 'fail'
                                        ? 'failing '
                                        : 'N/A '
                            }evaluation results`
                          : `Use AI to analyze patterns in ${runsToSummarizeCount} ${
                                evaluationSummaryFilter === 'all'
                                    ? ''
                                    : evaluationSummaryFilter === 'pass'
                                      ? 'passing '
                                      : evaluationSummaryFilter === 'fail'
                                        ? 'failing '
                                        : 'N/A '
                            }evaluation results`
                }
            >
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        posthog.capture(
                            evaluationSummary
                                ? 'llma evaluation regenerate clicked'
                                : 'llma evaluation summarize clicked',
                            {
                                filter: evaluationSummaryFilter,
                                runs_to_summarize: runsToSummarizeCount,
                            }
                        )
                        if (evaluationSummary) {
                            regenerateEvaluationSummary()
                        } else {
                            generateEvaluationSummary({})
                        }
                    }}
                    size="small"
                    disabled={runsToSummarizeCount === 0}
                    loading={evaluationSummaryLoading}
                    data-attr="llma-evaluation-summarize"
                >
                    {evaluationSummary ? 'Regenerate' : 'Summarize'}
                </LemonButton>
            </Tooltip>
            <LemonSegmentedButton
                value={evaluationSummaryFilter}
                onChange={(value) => {
                    posthog.capture('llma evaluation summary filter changed', {
                        filter: value,
                        previous_filter: evaluationSummaryFilter,
                    })
                    setEvaluationSummaryFilter(value as EvaluationSummaryFilter)
                }}
                options={[
                    { value: 'all', label: 'All' },
                    { value: 'pass', label: 'Passing' },
                    { value: 'fail', label: 'Failing' },
                    ...(evaluation?.output_config?.allows_na ? [{ value: 'na', label: 'N/A' }] : []),
                ]}
                size="small"
                data-attr="llma-evaluation-summary-filter"
            />
        </div>
    )
}

interface EvaluationSummaryPanelProps {
    runsLookup: Record<string, EvaluationRun>
}

export function EvaluationSummaryPanel({ runsLookup }: EvaluationSummaryPanelProps): JSX.Element | null {
    const {
        runsToSummarizeCount,
        evaluationSummary,
        evaluationSummaryLoading,
        evaluationSummaryFilter,
        summaryExpanded,
    } = useValues(llmEvaluationLogic)
    const { toggleSummaryExpanded } = useActions(llmEvaluationLogic)
    const showSummaryFeature = useFeatureFlag('LLM_ANALYTICS_EVALUATIONS_SUMMARY')

    if (!showSummaryFeature) {
        return null
    }

    if (evaluationSummaryLoading) {
        return (
            <div className="flex items-center justify-center py-6 border rounded-lg bg-bg-light">
                <Spinner className="text-primary" />
                <span className="ml-2 text-muted">Analyzing {runsToSummarizeCount} evaluation results...</span>
            </div>
        )
    }

    if (!evaluationSummary) {
        return null
    }

    return (
        <div className="border rounded-lg bg-bg-light">
            <button
                className="w-full flex items-center justify-between p-3 hover:bg-border-light transition-colors cursor-pointer"
                onClick={() => {
                    posthog.capture('llma evaluation summary toggled', {
                        expanded: !summaryExpanded,
                        filter: evaluationSummaryFilter,
                    })
                    toggleSummaryExpanded()
                }}
                data-attr="llma-evaluation-summary-toggle"
            >
                <div className="text-left">
                    <span className="font-semibold text-sm">AI Summary</span>
                    <span className="text-xs text-muted ml-2">
                        {evaluationSummary.statistics.total_analyzed} runs analyzed
                    </span>
                </div>
                <IconChevronDown className={`text-muted transition-transform ${summaryExpanded ? '' : '-rotate-90'}`} />
            </button>

            {summaryExpanded && (
                <div className="p-4 pt-0 space-y-4">
                    <div>
                        <p className="text-sm">{evaluationSummary.overall_assessment}</p>
                        <SummaryStatistics filter={evaluationSummaryFilter} statistics={evaluationSummary.statistics} />
                    </div>

                    {evaluationSummaryFilter === 'all' && (
                        <AllPatternsGrid evaluationSummary={evaluationSummary} runsLookup={runsLookup} />
                    )}

                    <FilteredPatternSection
                        filter={evaluationSummaryFilter}
                        evaluationSummary={evaluationSummary}
                        runsLookup={runsLookup}
                    />

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
    )
}

function SummaryStatistics({
    filter,
    statistics,
}: {
    filter: EvaluationSummaryFilter
    statistics: EvaluationSummary['statistics']
}): JSX.Element {
    return (
        <div className="mt-1 text-xs text-muted">
            {filter === 'all' && (
                <>
                    {statistics.pass_count} passed, {statistics.fail_count} failed
                    {statistics.na_count > 0 && <>, {statistics.na_count} N/A</>}
                </>
            )}
            {filter === 'pass' && <>{statistics.pass_count} passing runs analyzed</>}
            {filter === 'fail' && <>{statistics.fail_count} failing runs analyzed</>}
            {filter === 'na' && <>{statistics.na_count} N/A runs analyzed</>}
        </div>
    )
}

function AllPatternsGrid({
    evaluationSummary,
    runsLookup,
}: {
    evaluationSummary: EvaluationSummary
    runsLookup: Record<string, EvaluationRun>
}): JSX.Element | null {
    const hasPass = evaluationSummary.pass_patterns.length > 0
    const hasFail = evaluationSummary.fail_patterns.length > 0

    if (!hasPass && !hasFail) {
        return null
    }

    return (
        <div className={`grid gap-4 ${hasPass && hasFail ? 'grid-cols-2' : 'grid-cols-1'}`}>
            {hasPass && (
                <PatternList
                    patterns={evaluationSummary.pass_patterns}
                    type="pass"
                    label="Passing patterns"
                    icon={<IconCheck className="text-success" />}
                    runsLookup={runsLookup}
                />
            )}
            {hasFail && (
                <PatternList
                    patterns={evaluationSummary.fail_patterns}
                    type="fail"
                    label="Failing patterns"
                    icon={<IconX className="text-danger" />}
                    runsLookup={runsLookup}
                />
            )}
        </div>
    )
}

function PatternList({
    patterns,
    type,
    label,
    icon,
    runsLookup,
}: {
    patterns: EvaluationPattern[]
    type: 'pass' | 'fail' | 'na'
    label: string
    icon: JSX.Element
    runsLookup: Record<string, EvaluationRun>
}): JSX.Element {
    return (
        <div>
            <h4 className="font-semibold mb-2 flex items-center gap-2 text-sm">
                {icon}
                {label}
            </h4>
            <div className="space-y-2">
                {patterns.map((pattern, i) => (
                    <PatternCard key={i} pattern={pattern} type={type} runsLookup={runsLookup} />
                ))}
            </div>
        </div>
    )
}

const FILTER_CONFIG: Record<
    string,
    {
        patternsKey: 'pass_patterns' | 'fail_patterns' | 'na_patterns'
        icon: JSX.Element
        label: string
        type: 'pass' | 'fail' | 'na'
        emptyText: string
    }
> = {
    pass: {
        patternsKey: 'pass_patterns',
        icon: <IconCheck className="text-success" />,
        label: 'Passing patterns',
        type: 'pass',
        emptyText: 'No passing patterns identified',
    },
    fail: {
        patternsKey: 'fail_patterns',
        icon: <IconX className="text-danger" />,
        label: 'Failing patterns',
        type: 'fail',
        emptyText: 'No failing patterns identified',
    },
    na: {
        patternsKey: 'na_patterns',
        icon: <IconMinus className="text-muted" />,
        label: 'N/A patterns',
        type: 'na',
        emptyText: 'No N/A patterns identified',
    },
}

function FilteredPatternSection({
    filter,
    evaluationSummary,
    runsLookup,
}: {
    filter: EvaluationSummaryFilter
    evaluationSummary: EvaluationSummary
    runsLookup: Record<string, EvaluationRun>
}): JSX.Element | null {
    const section = FILTER_CONFIG[filter]
    if (!section) {
        return null
    }

    const patterns = evaluationSummary[section.patternsKey]

    return (
        <div>
            <h4 className="font-semibold mb-2 flex items-center gap-2 text-sm">
                {section.icon}
                {section.label}
            </h4>
            <div className="space-y-2">
                {patterns.length > 0 ? (
                    patterns.map((pattern, i) => (
                        <PatternCard key={i} pattern={pattern} type={section.type} runsLookup={runsLookup} />
                    ))
                ) : (
                    <p className="text-sm text-muted">{section.emptyText}</p>
                )}
            </div>
        </div>
    )
}
