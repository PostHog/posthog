import { ExperimentStatsMethod } from '~/types'

export interface StatsMethodOption {
    value: ExperimentStatsMethod
    title: string
    description: string
}

export const STATS_METHOD_OPTIONS: StatsMethodOption[] = [
    {
        value: ExperimentStatsMethod.Bayesian,
        title: 'Bayesian',
        description:
            'Gives you a clear win probability, showing how likely one variant is to be better than another. Great for product engineers new to experimentation.',
    },
    {
        value: ExperimentStatsMethod.Frequentist,
        title: 'Frequentist',
        description:
            'Uses p-values to determine statistical significance. Often preferred by data scientists and teams experienced with traditional A/B testing.',
    },
]
