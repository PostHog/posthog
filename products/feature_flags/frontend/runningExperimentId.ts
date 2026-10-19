import { FeatureFlagType } from '~/types'

export function runningExperimentId(featureFlag: Pick<FeatureFlagType, 'experiment_set_metadata'>): number | null {
    return featureFlag.experiment_set_metadata?.find((experiment) => experiment.is_running)?.id ?? null
}
