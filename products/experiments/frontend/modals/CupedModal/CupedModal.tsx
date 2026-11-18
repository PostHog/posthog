import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { CupedSelection } from 'scenes/experiments/ExperimentView/cuped'

import { MAX_LOOKBACK_DAYS, MIN_LOOKBACK_DAYS } from 'products/experiments/frontend/constants'
import { teamDefaultOptions } from 'products/experiments/frontend/modals/StatsMethodModal/useStatsMethodModal'

import { QuillCupedModal } from './QuillCupedModal'
import { CUPED_HELP, CUPED_LOOKBACK_HELP, useCupedModal } from './useCupedModal'

export function CupedModal(): JSX.Element {
    const model = useCupedModal()
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav && resultsRedesign) {
        return <QuillCupedModal model={model} />
    }
    const {
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
    } = model

    return (
        <LemonModal
            maxWidth={600}
            isOpen={isCupedModalOpen}
            onClose={onClose}
            // Cancel does not stop a running save. The save still applies, and its response replaces any new edit.
            closable={!experimentUpdateLoading}
            title="CUPED variance reduction"
            footer={
                <div className="flex items-center gap-2 justify-end">
                    <LemonButton type="secondary" onClick={onClose} disabledReason={savingReason}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={experimentUpdateLoading}
                        onClick={() => updateExperimentSettings({ stats_config: experiment.stats_config }, 'cuped')}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <p className="text-secondary m-0">{CUPED_HELP}</p>
                <div className="flex flex-col gap-1">
                    <LemonLabel>CUPED</LemonLabel>
                    <LemonSelect<CupedSelection>
                        value={selection}
                        onChange={updateSelection}
                        disabledReason={savingReason}
                        options={teamDefaultOptions(teamDefaultEnabled)}
                    />
                </div>
                {selection === 'enabled' && (
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Lookback window (days)</LemonLabel>
                        <LemonInput
                            type="number"
                            min={MIN_LOOKBACK_DAYS}
                            max={MAX_LOOKBACK_DAYS}
                            value={lookbackDays}
                            disabledReason={savingReason}
                            onChange={(value) => {
                                if (typeof value !== 'number' || !Number.isFinite(value)) {
                                    return
                                }
                                const rounded = Math.round(value)
                                if (rounded < MIN_LOOKBACK_DAYS || rounded > MAX_LOOKBACK_DAYS) {
                                    return
                                }
                                updateLookbackDays(rounded)
                            }}
                            className="w-32"
                        />
                        <p className="text-xs text-secondary m-0">{CUPED_LOOKBACK_HELP}</p>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
