import { useActions, useValues } from 'kea'

import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { CupedSelection, getCupedSelection, resolveCupedLookbackDays } from 'scenes/experiments/ExperimentView/cuped'
import { modalsLogic } from 'scenes/experiments/modalsLogic'
import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'

import { Experiment } from '~/types'

import { DEFAULT_LOOKBACK_DAYS, MAX_LOOKBACK_DAYS, MIN_LOOKBACK_DAYS } from 'products/experiments/frontend/constants'

export const CUPED_HELP =
    'Use pre-experiment data to detect significant effects faster. Currently supported for mean and funnel metrics.'
export const CUPED_LOOKBACK_HELP = `Number of days before the experiment start to use as the pre-experiment window. Must be between ${MIN_LOOKBACK_DAYS} and ${MAX_LOOKBACK_DAYS} days.`

export interface CupedModalModel {
    experiment: Experiment
    experimentUpdateLoading: boolean
    updateExperimentSettings: (update: Partial<Experiment>, fromModal?: 'cuped' | 'statsMethod') => void
    isCupedModalOpen: boolean
    savingReason?: string
    selection: CupedSelection
    teamDefaultEnabled: boolean
    lookbackDays: number
    onClose: () => void
    updateSelection: (next: CupedSelection) => void
    updateLookbackDays: (value: number) => void
}

export function useCupedModal(): CupedModalModel {
    const { experiment, experimentUpdateLoading } = useValues(experimentLogic)
    const { setExperiment, restoreUnmodifiedExperiment, updateExperimentSettings } = useActions(experimentLogic)
    const { experimentsConfig } = useValues(experimentsConfigLogic)
    const { closeCupedModal } = useActions(modalsLogic)
    const { isCupedModalOpen } = useValues(modalsLogic)
    const savingReason = experimentUpdateLoading ? 'Saving in progress' : undefined

    const selection = getCupedSelection(experiment.stats_config?.cuped)
    const teamDefaultEnabled = experimentsConfig?.default_cuped_enabled ?? false
    const teamDefaultLookbackDays = experimentsConfig?.default_cuped_lookback_days ?? null
    const lookbackDays = resolveCupedLookbackDays(
        experiment.stats_config?.cuped,
        teamDefaultLookbackDays,
        DEFAULT_LOOKBACK_DAYS
    )

    const onClose = (): void => {
        restoreUnmodifiedExperiment()
        closeCupedModal()
    }

    const updateSelection = (next: CupedSelection): void => {
        if (next === 'default') {
            // Drop the cuped key entirely so the team default applies at evaluation time.
            const { cuped: _cuped, ...restStatsConfig } = experiment.stats_config ?? {}
            setExperiment({ stats_config: restStatsConfig })
            return
        }
        setExperiment({
            stats_config: {
                ...experiment.stats_config,
                cuped: {
                    ...experiment.stats_config?.cuped,
                    enabled: next === 'enabled',
                },
            },
        })
    }

    const updateLookbackDays = (lookback_days: number): void => {
        setExperiment({
            stats_config: {
                ...experiment.stats_config,
                cuped: {
                    ...experiment.stats_config?.cuped,
                    lookback_days,
                },
            },
        })
    }

    return {
        experiment,
        experimentUpdateLoading,
        updateExperimentSettings,
        isCupedModalOpen,
        savingReason,
        selection,
        teamDefaultEnabled,
        lookbackDays,
        onClose,
        updateSelection,
        updateLookbackDays,
    }
}
