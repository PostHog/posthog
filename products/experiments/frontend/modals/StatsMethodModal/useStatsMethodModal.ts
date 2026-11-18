import { useActions, useValues } from 'kea'

import { experimentLogic } from 'scenes/experiments/experimentLogic'
import {
    DEFAULT_SEQUENTIAL_TUNING_PARAMETER,
    SequentialSelection,
    getSequentialSelection,
    resolveSequentialTuningParameter,
} from 'scenes/experiments/ExperimentView/sequential'
import { modalsLogic } from 'scenes/experiments/modalsLogic'
import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'

import { Experiment, ExperimentStatsMethod } from '~/types'

export function confidenceHelp(isBayesian: boolean, level: number): string {
    return isBayesian
        ? `At ${level * 100}%, we require a variant to have a ${level * 100}% or higher chance of being better before calling it a winner.`
        : `Higher confidence means we need stronger evidence before declaring a winner. ${level * 100}% confidence requires a p-value below ${(1 - level).toFixed(2)}.`
}

export const SEQUENTIAL_TESTING_HELP =
    'Always-valid p-values that are robust to peeking. You can check the experiment as often as you want without inflating the false positive rate, at the cost of slightly wider confidence intervals.'
export const TUNING_PARAMETER_HELP = `Roughly the sample size at which the confidence sequence is tightest. Set close to the expected total sample size of the experiment. Default is ${DEFAULT_SEQUENTIAL_TUNING_PARAMETER}.`

/** The options of a setting that can follow the team default, labelled with what the default is. */
export function teamDefaultOptions(
    teamDefaultEnabled: boolean
): { value: 'default' | 'enabled' | 'disabled'; label: string }[] {
    return [
        { value: 'default', label: `Use team default (${teamDefaultEnabled ? 'Enabled' : 'Disabled'})` },
        { value: 'enabled', label: 'Enabled' },
        { value: 'disabled', label: 'Disabled' },
    ]
}

export interface StatsMethodModalModel {
    experiment: Experiment
    statsMethod: ExperimentStatsMethod
    experimentUpdateLoading: boolean
    setExperiment: (experiment: Partial<Experiment>) => void
    updateExperimentSettings: (update: Partial<Experiment>, fromModal?: 'cuped' | 'statsMethod') => void
    isStatsEngineModalOpen: boolean
    savingReason?: string
    onClose: () => void
    isBayesian: boolean
    currentConfidenceLevel: number
    handleConfidenceLevelChange: (value: number) => void
    sequentialSelection: SequentialSelection
    teamDefaultSequentialEnabled: boolean
    sequentialTuningParameter: number
    updateSequentialSelection: (next: SequentialSelection) => void
    updateSequentialTuningParameter: (value: number) => void
}

export function useStatsMethodModal(): StatsMethodModalModel {
    const { experiment, statsMethod, experimentUpdateLoading } = useValues(experimentLogic)
    const { setExperiment, restoreUnmodifiedExperiment, updateExperimentSettings } = useActions(experimentLogic)
    const { closeStatsEngineModal } = useActions(modalsLogic)
    const { isStatsEngineModalOpen } = useValues(modalsLogic)
    const { experimentsConfig } = useValues(experimentsConfigLogic)
    const savingReason = experimentUpdateLoading ? 'Saving in progress' : undefined

    const onClose = (): void => {
        restoreUnmodifiedExperiment()
        closeStatsEngineModal()
    }

    const isBayesian = statsMethod === ExperimentStatsMethod.Bayesian

    // For Bayesian: ci_level (default 0.95)
    // For Frequentist: confidence = 1 - alpha (default alpha 0.05 = 95% confidence)
    const currentConfidenceLevel = isBayesian
        ? (experiment.stats_config?.bayesian?.ci_level ?? 0.95)
        : 1 - (experiment.stats_config?.frequentist?.alpha ?? 0.05)

    const handleConfidenceLevelChange = (value: number): void => {
        if (isBayesian) {
            setExperiment({
                stats_config: {
                    ...experiment.stats_config,
                    bayesian: {
                        ...experiment.stats_config?.bayesian,
                        ci_level: value,
                    },
                },
            })
        } else {
            setExperiment({
                stats_config: {
                    ...experiment.stats_config,
                    frequentist: {
                        ...experiment.stats_config?.frequentist,
                        alpha: 1 - value,
                    },
                },
            })
        }
    }

    const sequentialSelection = getSequentialSelection(experiment.stats_config?.frequentist)
    const teamDefaultSequentialEnabled = experimentsConfig?.default_sequential_testing_enabled ?? false
    const teamDefaultSequentialTuningParameter = experimentsConfig?.default_sequential_tuning_parameter ?? null
    const sequentialTuningParameter = resolveSequentialTuningParameter(
        experiment.stats_config?.frequentist,
        teamDefaultSequentialTuningParameter,
        DEFAULT_SEQUENTIAL_TUNING_PARAMETER
    )

    const updateSequentialSelection = (next: SequentialSelection): void => {
        const existingFrequentist = experiment.stats_config?.frequentist ?? {}
        if (next === 'default') {
            // Drop the sequential keys entirely so the team default applies at evaluation time.
            const {
                sequential_testing_enabled: _enabled,
                sequential_tuning_parameter: _param,
                ...restFrequentist
            } = existingFrequentist
            setExperiment({
                stats_config: {
                    ...experiment.stats_config,
                    frequentist: restFrequentist,
                },
            })
            return
        }
        setExperiment({
            stats_config: {
                ...experiment.stats_config,
                frequentist: {
                    ...existingFrequentist,
                    sequential_testing_enabled: next === 'enabled',
                },
            },
        })
    }

    const updateSequentialTuningParameter = (sequential_tuning_parameter: number): void => {
        setExperiment({
            stats_config: {
                ...experiment.stats_config,
                frequentist: {
                    ...experiment.stats_config?.frequentist,
                    sequential_tuning_parameter,
                },
            },
        })
    }

    return {
        experiment,
        statsMethod,
        experimentUpdateLoading,
        setExperiment,
        updateExperimentSettings,
        isStatsEngineModalOpen,
        savingReason,
        onClose,
        isBayesian,
        currentConfidenceLevel,
        handleConfidenceLevelChange,
        sequentialSelection,
        teamDefaultSequentialEnabled,
        sequentialTuningParameter,
        updateSequentialSelection,
        updateSequentialTuningParameter,
    }
}
