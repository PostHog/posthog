import { Experiment, ExperimentStatsMethod } from '~/types'

import { ExperimentStatusInput, hasEnded, isLaunched } from 'products/experiments/frontend/experimentStatus'

export type ExperimentMetaBarInput = NonNullable<ExperimentStatusInput> & Pick<Experiment, 'conclusion'>

export interface ExperimentMetaBarVisibility {
    showDateRange: boolean
    showRemainingTime: boolean
    showRefresh: boolean
    showConclusion: boolean
}

// A completed experiment has final results, so refreshing and counting down make no sense for it.
export function getExperimentMetaBarVisibility(experiment: ExperimentMetaBarInput): ExperimentMetaBarVisibility {
    const launched = isLaunched(experiment)
    const ended = hasEnded(experiment)

    return {
        showDateRange: launched,
        showRemainingTime: !ended,
        showRefresh: launched && !ended,
        showConclusion: ended && !!experiment.conclusion,
    }
}

export interface ExperimentStatsSummary {
    method: 'Bayesian' | 'Frequentist'
    level: string
    description: string
}

export function getExperimentStatsSummary(
    experiment: Pick<Experiment, 'stats_config'>,
    statsMethod: ExperimentStatsMethod
): ExperimentStatsSummary {
    if (statsMethod === ExperimentStatsMethod.Bayesian) {
        const level = `${((experiment.stats_config?.bayesian?.ci_level ?? 0.95) * 100).toFixed(0)}%`
        return { method: 'Bayesian', level, description: `Bayesian statistics with a ${level} credible interval` }
    }

    const level = `${((1 - (experiment.stats_config?.frequentist?.alpha ?? 0.05)) * 100).toFixed(0)}%`
    return { method: 'Frequentist', level, description: `Frequentist statistics with a ${level} confidence level` }
}
