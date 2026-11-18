import { LemonButton, LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { LemonModal } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { MAX_SEQUENTIAL_TUNING_PARAMETER, SequentialSelection } from 'scenes/experiments/ExperimentView/sequential'

import { StatsMethodSelector } from 'products/experiments/frontend/components/StatsMethodSelector'
import { CONFIDENCE_LEVEL_OPTIONS } from 'products/experiments/frontend/constants'

import { QuillStatsMethodModal } from './QuillStatsMethodModal'
import {
    SEQUENTIAL_TESTING_HELP,
    TUNING_PARAMETER_HELP,
    confidenceHelp,
    teamDefaultOptions,
    useStatsMethodModal,
} from './useStatsMethodModal'

export function StatsMethodModal(): JSX.Element {
    const model = useStatsMethodModal()
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav && resultsRedesign) {
        return <QuillStatsMethodModal model={model} />
    }
    const {
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
    } = model

    return (
        <LemonModal
            maxWidth={600}
            isOpen={isStatsEngineModalOpen}
            onClose={onClose}
            // Cancel does not stop a running save. The save still applies, and its response replaces any new edit.
            closable={!experimentUpdateLoading}
            title="Statistics configuration"
            footer={
                <div className="flex items-center gap-2 justify-end">
                    <LemonButton type="secondary" onClick={onClose} disabledReason={savingReason}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={experimentUpdateLoading}
                        onClick={() =>
                            updateExperimentSettings({ stats_config: experiment.stats_config }, 'statsMethod')
                        }
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="mb-4">
                <StatsMethodSelector
                    value={statsMethod}
                    disabled={experimentUpdateLoading}
                    disabledReason={savingReason}
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
                    disabledReason={savingReason}
                    options={CONFIDENCE_LEVEL_OPTIONS}
                    className="w-24"
                />
                <p className="text-xs text-secondary m-0">{confidenceHelp(isBayesian, currentConfidenceLevel)}</p>
            </div>
            {!isBayesian && (
                <div className="flex flex-col gap-2 mt-4">
                    <LemonLabel>Sequential testing</LemonLabel>
                    <LemonSelect<SequentialSelection>
                        value={sequentialSelection}
                        onChange={updateSequentialSelection}
                        disabledReason={savingReason}
                        options={teamDefaultOptions(teamDefaultSequentialEnabled)}
                        className="w-72"
                    />
                    <p className="text-xs text-secondary m-0">{SEQUENTIAL_TESTING_HELP}</p>
                    {sequentialSelection === 'enabled' && (
                        <div className="flex flex-col gap-1 mt-1">
                            <LemonLabel>Tuning parameter</LemonLabel>
                            <LemonInput
                                type="number"
                                min={1}
                                max={MAX_SEQUENTIAL_TUNING_PARAMETER}
                                value={sequentialTuningParameter}
                                disabledReason={savingReason}
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
                            <p className="text-xs text-secondary m-0">{TUNING_PARAMETER_HELP}</p>
                        </div>
                    )}
                </div>
            )}
        </LemonModal>
    )
}
