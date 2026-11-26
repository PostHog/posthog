import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'

import {
    deleteDisabledReason,
    isDeprecatePayload,
    noReadsLabel,
    refreshCostLabel,
    refreshesTheView,
} from '../suggestionCopy'
import { DeprecateAction, catalogEditBlockedReason, warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export type RefreshChoice = 'stop' | 'keep'

interface DeprecateActionCopy {
    title: (subjectName: string) => string
    confirmLabel: string
    confirmDataAttr: string
}

export const DEPRECATE_ACTION_COPY: Record<DeprecateAction, DeprecateActionCopy> = {
    deprecate: {
        title: (subjectName) => `Mark ${subjectName} as deprecated?`,
        confirmLabel: 'Mark deprecated',
        confirmDataAttr: 'warehouse-suggestions-deprecate-confirm',
    },
    unmarked: {
        title: (subjectName) => `Stop refreshing ${subjectName}?`,
        confirmLabel: 'Stop refreshing',
        confirmDataAttr: 'warehouse-suggestions-stop-only-confirm',
    },
    delete: {
        title: (subjectName) => `Delete ${subjectName}?`,
        confirmLabel: 'Delete view',
        confirmDataAttr: 'warehouse-suggestions-delete-confirm',
    },
}

const NOTHING_TO_CHANGE_REASON = 'Nothing would change. Stop refreshing it, or dismiss the suggestion instead.'

const ACTION_CHOICES: LemonRadioOption<DeprecateAction>[] = [
    {
        value: 'deprecate',
        label: 'Mark it deprecated',
        description: 'It stays in the data catalog with a deprecated label, so people know not to use it.',
        'data-attr': 'warehouse-suggestions-deprecate-mark',
    },
    {
        value: 'unmarked',
        label: "Don't mark it deprecated",
        description: "If no one reads it in the next 30 days, it's suggested for deprecation again.",
        'data-attr': 'warehouse-suggestions-deprecate-unmarked',
    },
    {
        value: 'delete',
        label: 'Delete it',
        description: "Deletes the view and its stored table. You can't undo this.",
        'data-attr': 'warehouse-suggestions-deprecate-delete',
    },
]

export const REFRESH_CHOICES: LemonRadioOption<RefreshChoice>[] = [
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

export function deprecateActionChoices(
    materialized: boolean,
    blockedReasons: Record<DeprecateAction, string | undefined>
): LemonRadioOption<DeprecateAction>[] {
    return ACTION_CHOICES.filter((choice) => materialized || choice.value !== 'unmarked').map((choice) => ({
        ...choice,
        disabledReason: blockedReasons[choice.value],
    }))
}

export function confirmDisabledReason(
    deprecateAction: DeprecateAction,
    keepMaterialized: boolean,
    blockedReasons: Record<DeprecateAction, string | undefined>
): string | undefined {
    if (deprecateAction === 'unmarked' && keepMaterialized) {
        return NOTHING_TO_CHANGE_REASON
    }
    return blockedReasons[deprecateAction]
}

export function DeprecateSuggestionModal(): JSX.Element | null {
    const { acceptConfirmSuggestion, actionsInFlight, deprecateAction, keepMaterialized, status } =
        useValues(warehouseSuggestionsLogic)
    const { confirmAccept, closeAcceptConfirm, setDeprecateAction, setKeepMaterialized } =
        useActions(warehouseSuggestionsLogic)
    const payload = acceptConfirmSuggestion?.payload

    if (!acceptConfirmSuggestion || !payload || !isDeprecatePayload(payload)) {
        return null
    }
    const inFlight = !!actionsInFlight[acceptConfirmSuggestion.id]
    const materialized = refreshesTheView(payload)
    const windowDays = status?.window_days ?? 0
    const noReads = noReadsLabel(windowDays)
    const blockedReasons: Record<DeprecateAction, string | undefined> = {
        deprecate: catalogEditBlockedReason(),
        unmarked: undefined,
        delete: deleteDisabledReason(acceptConfirmSuggestion.evidence, windowDays),
    }
    const copy = DEPRECATE_ACTION_COPY[deprecateAction]

    return (
        <LemonModal
            isOpen
            closable={!inFlight}
            onClose={closeAcceptConfirm}
            title={copy.title(payload.subject_name)}
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
                        status={deprecateAction === 'delete' ? 'danger' : undefined}
                        loading={inFlight}
                        disabledReason={confirmDisabledReason(deprecateAction, keepMaterialized, blockedReasons)}
                        onClick={() => confirmAccept()}
                        data-attr={copy.confirmDataAttr}
                    >
                        {copy.confirmLabel}
                    </LemonButton>
                </>
            }
        >
            <div className="flex max-w-xl flex-col gap-4">
                <p className="m-0 text-sm text-secondary">
                    {materialized ? `${noReads}. ${refreshCostLabel(payload)}.` : `${noReads}.`}
                </p>
                <fieldset disabled={inFlight} className="flex flex-col gap-2">
                    <h4 className="m-0 text-sm font-semibold">What to do</h4>
                    <LemonRadio
                        aria-label="What to do"
                        value={deprecateAction}
                        onChange={setDeprecateAction}
                        options={deprecateActionChoices(materialized, blockedReasons)}
                        radioPosition="top"
                    />
                </fieldset>
                {materialized && deprecateAction !== 'delete' && (
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
                )}
            </div>
        </LemonModal>
    )
}
