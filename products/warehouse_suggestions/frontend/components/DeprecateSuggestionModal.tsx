import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'

import { isDeprecatePayload, noReadsLabel, refreshCostLabel } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

type RefreshChoice = 'stop' | 'keep'

const REFRESH_CHOICES: LemonRadioOption<RefreshChoice>[] = [
    {
        value: 'stop',
        label: 'Stop refreshing it',
        description:
            'Deletes its stored table and stops its refreshes, if it still has them. PostHog keeps them when another view or a sync reads it. You can materialize it again later.',
        'data-attr': 'warehouse-suggestions-deprecate-stop-refreshing',
    },
    {
        value: 'keep',
        label: 'Keep refreshing it',
        description: 'It stays materialized, and its refreshes keep their cost.',
        'data-attr': 'warehouse-suggestions-deprecate-keep-refreshing',
    },
]

export function DeprecateSuggestionModal(): JSX.Element | null {
    const { acceptConfirmSuggestion, actionsInFlight, keepMaterialized, status } = useValues(warehouseSuggestionsLogic)
    const { confirmAccept, closeAcceptConfirm, setKeepMaterialized } = useActions(warehouseSuggestionsLogic)
    const payload = acceptConfirmSuggestion?.payload

    if (!acceptConfirmSuggestion || !payload || !isDeprecatePayload(payload)) {
        return null
    }
    const inFlight = !!actionsInFlight[acceptConfirmSuggestion.id]

    return (
        <LemonModal
            isOpen
            closable={!inFlight}
            onClose={closeAcceptConfirm}
            title={`Mark ${payload.subject_name} as deprecated?`}
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
                        data-attr="warehouse-suggestions-deprecate-confirm"
                    >
                        Mark deprecated
                    </LemonButton>
                </>
            }
        >
            <div className="flex max-w-xl flex-col gap-4">
                <p className="m-0 text-sm text-secondary">
                    {`${noReadsLabel(status?.window_days ?? 0)}. ${refreshCostLabel(payload)}.`}
                </p>
                <fieldset disabled={inFlight} className="flex flex-col gap-2">
                    <h4 className="m-0 text-sm font-semibold">Its materialization</h4>
                    <LemonRadio
                        aria-label="Its materialization"
                        value={keepMaterialized ? 'keep' : 'stop'}
                        onChange={(choice) => setKeepMaterialized(choice === 'keep')}
                        options={REFRESH_CHOICES}
                        radioPosition="top"
                    />
                </fieldset>
            </div>
        </LemonModal>
    )
}
