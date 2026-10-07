import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { SyncFrequencySelect } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'

import { INTERVAL_SECONDS } from '../refreshIntervals'
import { isMaterializePayload } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export function MaterializeSuggestionModal(): JSX.Element | null {
    const { materializeModalSuggestion, materializeError, materializeInterval, actionsInFlight } =
        useValues(warehouseSuggestionsLogic)
    const { acceptSuggestion, closeMaterializeModal, setMaterializeInterval } = useActions(warehouseSuggestionsLogic)
    const payload = materializeModalSuggestion?.payload

    if (!materializeModalSuggestion || !payload || !isMaterializePayload(payload)) {
        return null
    }
    const inFlight = !!actionsInFlight[materializeModalSuggestion.id]

    return (
        <LemonModal
            isOpen
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
                        disabledReason={materializeInterval ? undefined : 'Pick how often it refreshes'}
                        onClick={() =>
                            materializeInterval &&
                            acceptSuggestion(materializeModalSuggestion.id, INTERVAL_SECONDS[materializeInterval])
                        }
                        data-attr="warehouse-suggestions-materialize-confirm"
                    >
                        Materialize
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <p className="m-0 text-sm">
                    Stores the result and refreshes it on this schedule. Reads of this view use the stored rows. Pick a
                    longer schedule if the data doesn't need to be this fresh.
                </p>
                <SyncFrequencySelect value={materializeInterval} onChange={setMaterializeInterval} loading={inFlight} />
                {materializeError && <LemonBanner type="error">{materializeError} Pick another schedule.</LemonBanner>}
            </div>
        </LemonModal>
    )
}
