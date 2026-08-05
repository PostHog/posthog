import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { LemonModal } from '@posthog/lemon-ui'

import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'

import { ExperimentStatsMethod } from '~/types'

import { StatsMethodSelector } from '../components/StatsMethodSelector'
import { CONFIDENCE_LEVEL_OPTIONS } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import {
    DEFAULT_SEQUENTIAL_TUNING_PARAMETER,
    MAX_SEQUENTIAL_TUNING_PARAMETER,
    SequentialSelection,
    getSequentialSelection,
    resolveSequentialTuningParameter,
} from './sequential'

export function StatsMethodModal(): JSX.Element {
    const { experiment, statsMethod } = useValues(experimentLogic)
    const { updateExperimentSettings, setExperiment, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { closeStatsEngineModal } = useActions(modalsLogic)
    const { isStatsEngineModalOpen } = useValues(modalsLogic)
    const { experimentsConfig } = useValues(experimentsConfigLogic)

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

    return (
        <LemonModal
            maxWidth={600}
            isOpen={isStatsEngineModalOpen}
            onClose={onClose}
            title="Statistics configuration"
            footer={
                <div className="flex items-center gap-2 justify-end">
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            updateExperimentSettings({ stats_config: experiment.stats_config })
                            closeStatsEngineModal()
                        }}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="mb-4">
                <StatsMethodSelector
                    value={statsMethod}
                    onChange={(newStatsMethod) => {
                        setExperiment({
                            stats_config: {
                                ...experiment.stats_config,
                                method: newStatsMethod,
                            },
                        })
                    }}
                />
            </div>
            <div className="flex flex-col gap-2">
                <LemonLabel>Confidence level</LemonLabel>
                <LemonSelect
                    value={currentConfidenceLevel}
                    onChange={handleConfidenceLevelChange}
                    options={CONFIDENCE_LEVEL_OPTIONS}
                    className="w-24"
                />
                <p className="text-xs text-secondary m-0">
                    {isBayesian
                        ? `At ${currentConfidenceLevel * 100}%, we require a variant to have a ${currentConfidenceLevel * 100}% or higher chance of being better before calling it a winner.`
                        : `Higher confidence means we need stronger evidence before declaring a winner. ${currentConfidenceLevel * 100}% confidence requires a p-value below ${(1 - currentConfidenceLevel).toFixed(2)}.`}
                </p>
            </div>
            {!isBayesian && (
                <div className="flex flex-col gap-2 mt-4">
                    <LemonLabel>Sequential testing</LemonLabel>
                    <LemonSelect<SequentialSelection>
                        value={sequentialSelection}
                        onChange={updateSequentialSelection}
                        options={[
                            {
                                value: 'default',
                                label: `Use team default (${teamDefaultSequentialEnabled ? 'Enabled' : 'Disabled'})`,
                            },
                            { value: 'enabled', label: 'Enabled' },
                            { value: 'disabled', label: 'Disabled' },
                        ]}
                        className="w-72"
                    />
                    <p className="text-xs text-secondary m-0">
                        Always-valid p-values that are robust to peeking. You can check the experiment as often as you
                        want without inflating the false positive rate, at the cost of slightly wider confidence
                        intervals.
                    </p>
                    {sequentialSelection === 'enabled' && (
                        <div className="flex flex-col gap-1 mt-1">
                            <LemonLabel>Tuning parameter</LemonLabel>
                            <LemonInput
                                type="number"
                                min={1}
                                max={MAX_SEQUENTIAL_TUNING_PARAMETER}
                                value={sequentialTuningParameter}
                                onChange={(value) => {
                                    if (
                                        typeof value !== 'number' ||
                                        !Number.isFinite(value) ||
                                        value < 1 ||
                                        value > MAX_SEQUENTIAL_TUNING_PARAMETER
                                    ) {
                                        return
                                    }
                                    updateSequentialTuningParameter(Math.round(value))
                                }}
                                className="w-32"
                            />
                            <p className="text-xs text-secondary m-0">
                                Roughly the sample size at which the confidence sequence is tightest. Set close to the
                                expected total sample size of the experiment. Default is{' '}
                                {DEFAULT_SEQUENTIAL_TUNING_PARAMETER}.
                            </p>
                        </div>
                    )}
                </div>
            )}
        </LemonModal>
    )
}
