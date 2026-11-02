import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import {
    INCREMENTAL_CHECK_LOADING,
    IncrementalConfigOptions,
} from 'scenes/data-warehouse/editor/IncrementalConfigFields'
import { CADENCE_LABELS, SyncFrequencySelect } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'

import { INTERVAL_SECONDS, intervalForSeconds } from '../refreshIntervals'
import {
    dataAgeLabel,
    isMaterializePayload,
    materializeSaving,
    refreshModeLabel,
    savingSentence,
    shorterScheduleWarning,
    suggestedScheduleHint,
    todayAgeLabel,
} from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DataAgeMeta } from './DataAgeMeta'

export function MaterializeSuggestionModal(): JSX.Element | null {
    const {
        materializeModalSuggestion,
        materializeError,
        materializeInterval,
        materializeIntervalShorterThanSuggested,
        materializeDisabledReason,
        actionsInFlight,
        refreshDraft,
        incrementalCheck,
        incrementalCheckLoading,
    } = useValues(warehouseSuggestionsLogic)
    const { confirmMaterialize, closeMaterializeModal, setMaterializeInterval, setRefreshDraft } =
        useActions(warehouseSuggestionsLogic)
    const payload = materializeModalSuggestion?.payload

    if (!materializeModalSuggestion || !payload || !isMaterializePayload(payload)) {
        return null
    }
    const inFlight = !!actionsInFlight[materializeModalSuggestion.id]
    const suggestedInterval = intervalForSeconds(payload.refresh_interval_seconds)
    const suggestedCadence = suggestedInterval ? CADENCE_LABELS[suggestedInterval] : null
    const pickedSeconds = materializeInterval ? INTERVAL_SECONDS[materializeInterval] : payload.refresh_interval_seconds
    const shorterWarning =
        materializeIntervalShorterThanSuggested && suggestedCadence
            ? shorterScheduleWarning(payload.refresh_interval_basis, suggestedCadence)
            : null

    return (
        <LemonModal
            isOpen
            closable={!inFlight}
            onClose={closeMaterializeModal}
            title={`Materialize ${payload.subject_name}`}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeMaterializeModal}
                        disabledReason={inFlight ? 'Working' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={inFlight}
                        disabledReason={materializeDisabledReason ?? undefined}
                        onClick={() => confirmMaterialize()}
                        data-attr="warehouse-suggestions-materialize-confirm"
                    >
                        Materialize
                    </LemonButton>
                </>
            }
        >
            <div className="flex max-w-xl flex-col gap-4">
                <p className="m-0 text-sm text-secondary">
                    Stores the result and refreshes it on a schedule. Reads of this view use the stored rows.
                </p>
                <div className="flex flex-col gap-1.5">
                    <SyncFrequencySelect
                        value={materializeInterval}
                        onChange={setMaterializeInterval}
                        loading={inFlight}
                    />
                    {suggestedCadence && (
                        <span className="text-xs text-secondary">
                            {suggestedScheduleHint(payload.refresh_interval_basis, suggestedCadence)}
                        </span>
                    )}
                </div>
                <fieldset disabled={inFlight} className="flex flex-col">
                    <h4 className="m-0 text-sm font-semibold">Refresh mode</h4>
                    <IncrementalConfigOptions
                        check={incrementalCheckLoading ? INCREMENTAL_CHECK_LOADING : incrementalCheck}
                        draft={refreshDraft}
                        onChange={setRefreshDraft}
                    />
                </fieldset>
                <div className="grid grid-cols-1 gap-3 rounded border border-primary px-3 py-2.5">
                    <div className="flex flex-col gap-0.5">
                        <span className="text-xs font-semibold text-secondary">With these settings</span>
                        <span className="text-sm">
                            <DataAgeMeta age={dataAgeLabel(payload, pickedSeconds)} />
                        </span>
                        <span className="text-xs text-secondary">{todayAgeLabel(payload)}</span>
                        <span className="text-xs text-secondary">
                            {refreshModeLabel(refreshDraft.enabled, refreshDraft.incrementalKey)}
                        </span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                        <span className="text-xs font-semibold text-secondary">
                            Estimated at the suggested settings
                        </span>
                        <span className="text-sm">{savingSentence(materializeSaving(payload))}</span>
                    </div>
                </div>
                {shorterWarning && <LemonBanner type="warning">{shorterWarning}</LemonBanner>}
                {materializeError && <LemonBanner type="error">{materializeError}</LemonBanner>}
            </div>
        </LemonModal>
    )
}
