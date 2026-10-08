import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { CachedNewExperimentQueryResponse, ExperimentMetric } from '~/queries/schema/schema-general'
import { experimentMetricsLogic } from '~/scenes/experiments/experimentMetricsLogic'
import { getChanceToWin, isBayesianResult } from '~/scenes/experiments/MetricsView/shared/utils'
import { Experiment } from '~/types'

import { ResultsTag } from 'products/experiments/frontend/components/ResultsTag'

import { NotebookCompactTable } from './NotebookCompactTable'
import { NotebookWinningVariantSummary } from './NotebookWinningVariantSummary'

type MetricWithResult = {
    metric: ExperimentMetric
    result: CachedNewExperimentQueryResponse
    index: number
    maxChanceToWin: number
    isSignificant: boolean
}

function findMostSignificantMetric(
    metrics: ExperimentMetric[] | undefined,
    results: CachedNewExperimentQueryResponse[] | undefined
): MetricWithResult | null {
    if (!metrics?.length || !results?.length) {
        return null
    }

    return metrics
        .map((metric, index) => {
            const result = results[index]
            if (!result?.variant_results?.length) {
                return null
            }

            const goal = 'goal' in metric ? metric.goal : undefined
            const isSignificant = result.variant_results.some((v) => v.significant)
            const maxChanceToWin = result.variant_results
                .filter(isBayesianResult)
                .map((v) => getChanceToWin(v, goal) ?? 0)
                .reduce((max, ctw) => Math.max(max, ctw), 0)

            return { metric, result, index, maxChanceToWin, isSignificant }
        })
        .filter((m): m is MetricWithResult => m !== null)
        .reduce((best, current) => {
            if (current.isSignificant && !best.isSignificant) {
                return current
            }
            if (current.isSignificant === best.isSignificant && current.maxChanceToWin > best.maxChanceToWin) {
                return current
            }
            return best
        }, null)
}

export function NotebookExperimentResults({
    experiment,
    expanded,
}: {
    experiment: Experiment
    expanded: boolean
}): JSX.Element | null {
    const { primaryMetricsResults, isRecalculating } = useValues(experimentMetricsLogic({ experiment }))

    const bestMetric = isRecalculating
        ? null
        : findMostSignificantMetric(experiment.metrics as ExperimentMetric[] | undefined, primaryMetricsResults)

    const totalPrimaryMetrics = experiment.metrics?.length || 0

    if (!expanded) {
        return bestMetric ? <ResultsTag isSignificant={bestMetric.isSignificant} /> : null
    }

    if (isRecalculating) {
        return (
            <div className="space-y-2">
                <LemonSkeleton className="h-4 w-48" />
                <LemonSkeleton className="h-24 w-full" />
            </div>
        )
    }

    if (bestMetric) {
        return (
            <>
                {totalPrimaryMetrics > 1 && (
                    <div className="text-xs text-muted mb-1">
                        Showing most significant of {totalPrimaryMetrics} metrics
                        {bestMetric.metric.name && `: ${bestMetric.metric.name}`}
                    </div>
                )}
                <NotebookWinningVariantSummary result={bestMetric.result} metric={bestMetric.metric} />
                <NotebookCompactTable result={bestMetric.result} metric={bestMetric.metric} />
            </>
        )
    }
    return <div className="text-sm text-muted">Collecting data...</div>
}
