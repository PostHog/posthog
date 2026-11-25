import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    FieldGroup,
} from '@posthog/quill'

import {
    deleteDisabledReason,
    isDeprecatePayload,
    noReadsLabel,
    refreshCostLabel,
    refreshesTheView,
} from '../suggestionCopy'
import { DeprecateAction, catalogEditBlockedReason, warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import {
    DEPRECATE_ACTION_COPY,
    REFRESH_CHOICES,
    RefreshChoice,
    confirmDisabledReason,
    deprecateActionChoices,
} from './DeprecateSuggestionModal'
import { QuillChoiceGroup } from './QuillChoiceGroup'

const ACTION_LEGEND = 'What to do'
const MATERIALIZATION_LEGEND = 'Its materialization'

export function QuillDeprecateSuggestionModal(): JSX.Element | null {
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
        <Dialog open onOpenChange={(open: boolean) => !open && !inFlight && closeAcceptConfirm()}>
            <DialogContent size="wide" className="max-w-xl" showCloseButton={!inFlight}>
                <DialogHeader>
                    <DialogTitle>{copy.title(payload.subject_name)}</DialogTitle>
                    <DialogDescription>
                        {materialized ? `${noReads}. ${refreshCostLabel(payload)}.` : `${noReads}.`}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <QuillChoiceGroup<DeprecateAction>
                            legend={ACTION_LEGEND}
                            idPrefix="deprecate-action"
                            value={deprecateAction}
                            onChange={setDeprecateAction}
                            choices={deprecateActionChoices(materialized, blockedReasons)}
                            disabled={inFlight}
                        />
                        {materialized && deprecateAction !== 'delete' && (
                            <QuillChoiceGroup<RefreshChoice>
                                legend={MATERIALIZATION_LEGEND}
                                idPrefix="deprecate-refresh"
                                value={keepMaterialized ? 'keep' : 'stop'}
                                onChange={(choice) => setKeepMaterialized(choice === 'keep')}
                                choices={REFRESH_CHOICES}
                                disabled={inFlight}
                            />
                        )}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeAcceptConfirm}
                        disabledReason={inFlight ? 'Working' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant={deprecateAction === 'delete' ? 'destructive-outline' : 'primary'}
                        loading={inFlight}
                        disabledReason={confirmDisabledReason(deprecateAction, keepMaterialized, blockedReasons)}
                        onClick={() => confirmAccept()}
                        data-attr={copy.confirmDataAttr}
                    >
                        {copy.confirmLabel}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
