import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import {
    isUnmaterializePayload,
    monthlyCost,
    readTimeLabel,
    savingSentence,
    unmaterializeSaving,
} from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export function UnmaterializeSuggestionModal(): JSX.Element | null {
    const { acceptConfirmSuggestion, actionsInFlight } = useValues(warehouseSuggestionsLogic)
    const { confirmAccept, closeAcceptConfirm } = useActions(warehouseSuggestionsLogic)
    const payload = acceptConfirmSuggestion?.payload

    if (!acceptConfirmSuggestion || !payload || !isUnmaterializePayload(payload)) {
        return null
    }
    const inFlight = !!actionsInFlight[acceptConfirmSuggestion.id]
    const saving = unmaterializeSaving(payload)

    return (
        <LemonModal
            isOpen
            closable={!inFlight}
            onClose={closeAcceptConfirm}
            title={`Stop materializing ${payload.subject_name}?`}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeAcceptConfirm}
                        disabledReason={inFlight ? 'Working' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={inFlight}
                        onClick={() => confirmAccept()}
                        data-attr="warehouse-suggestions-unmaterialize-confirm"
                    >
                        Stop materializing
                    </LemonButton>
                </>
            }
        >
            <div className="flex max-w-xl flex-col gap-4">
                <p className="m-0 text-sm text-secondary">
                    Deletes its stored table and stops its refreshes. Each read computes the view from its query
                    instead. You can materialize it again later.
                </p>
                <div className="grid grid-cols-1 gap-3 rounded border border-primary px-3 py-2.5">
                    <div className="flex flex-col gap-0.5">
                        <span className="text-xs font-semibold text-secondary">Materialized now</span>
                        <span className="text-sm">
                            {monthlyCost({
                                seconds: payload.refresh_seconds_per_month,
                                bytes: payload.refresh_bytes_per_month,
                            })}
                        </span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                        <span className="text-xs font-semibold text-secondary">Computed on each read</span>
                        <span className="text-sm">
                            {`${monthlyCost({ seconds: payload.live_seconds_per_month, bytes: payload.live_bytes_per_month })} (estimate)`}
                        </span>
                        <span className="text-xs text-secondary">{readTimeLabel(payload.read_seconds)}</span>
                    </div>
                    <span className="text-sm font-semibold text-success">{savingSentence(saving)}</span>
                </div>
            </div>
        </LemonModal>
    )
}
