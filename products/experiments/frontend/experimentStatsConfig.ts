import { Experiment, ExperimentStatsMethod } from '~/types'

// Bayesian stores the level the results are computed at, frequentist stores the alpha it complements.
export function getExperimentStatsLevel(
    experiment: Pick<Experiment, 'stats_config'>,
    statsMethod: ExperimentStatsMethod
): string {
    if (statsMethod === ExperimentStatsMethod.Bayesian) {
        return `${((experiment.stats_config?.bayesian?.ci_level ?? 0.95) * 100).toFixed(0)}%`
    }
    return `${((1 - (experiment.stats_config?.frequentist?.alpha ?? 0.05)) * 100).toFixed(0)}%`
}
