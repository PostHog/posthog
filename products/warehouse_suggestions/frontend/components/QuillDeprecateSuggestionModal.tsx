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

import { deleteDisabledReason, isDeprecatePayload, noReadsLabel, refreshCostLabel } from '../suggestionCopy'
import { catalogEditBlockedReason, warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { ACTION_CHOICES, ActionChoice, REFRESH_CHOICES, RefreshChoice } from './DeprecateSuggestionModal'
import { QuillChoiceGroup } from './QuillChoiceGroup'

const ACTION_LEGEND = 'What to do'
const MATERIALIZATION_LEGEND = 'Its materialization'

export function QuillDeprecateSuggestionModal(): JSX.Element | null {
    const { acceptConfirmSuggestion, actionsInFlight, deleteView, keepMaterialized, status } =
        useValues(warehouseSuggestionsLogic)
    const { confirmAccept, closeAcceptConfirm, setDeleteView, setKeepMaterialized } =
        useActions(warehouseSuggestionsLogic)
    const payload = acceptConfirmSuggestion?.payload

    if (!acceptConfirmSuggestion || !payload || !isDeprecatePayload(payload)) {
        return null
    }
    const inFlight = !!actionsInFlight[acceptConfirmSuggestion.id]
    const materialized = payload.materialized !== false
    const windowDays = status?.window_days ?? 0
    const noReads = noReadsLabel(windowDays)
    const blockedReasons: Record<ActionChoice, string | undefined> = {
        deprecate: catalogEditBlockedReason(),
        delete: deleteDisabledReason(acceptConfirmSuggestion.evidence, windowDays),
    }
    const actionChoices = ACTION_CHOICES.map((choice) => ({ ...choice, disabledReason: blockedReasons[choice.value] }))
    const chosen: ActionChoice = deleteView ? 'delete' : 'deprecate'

    return (
        <Dialog open onOpenChange={(open: boolean) => !open && !inFlight && closeAcceptConfirm()}>
            <DialogContent size="wide" className="max-w-xl" showCloseButton={!inFlight}>
                <DialogHeader>
                    <DialogTitle>
                        {deleteView ? `Delete ${payload.subject_name}?` : `Mark ${payload.subject_name} as deprecated?`}
                    </DialogTitle>
                    <DialogDescription>
                        {materialized ? `${noReads}. ${refreshCostLabel(payload)}.` : `${noReads}.`}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <QuillChoiceGroup<ActionChoice>
                            legend={ACTION_LEGEND}
                            idPrefix="deprecate-action"
                            value={chosen}
                            onChange={(choice) => setDeleteView(choice === 'delete')}
                            choices={actionChoices}
                            disabled={inFlight}
                        />
                        {materialized && !deleteView && (
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
                        variant={deleteView ? 'destructive-outline' : 'primary'}
                        loading={inFlight}
                        disabledReason={blockedReasons[chosen]}
                        onClick={() => confirmAccept()}
                        data-attr={
                            deleteView
                                ? 'warehouse-suggestions-delete-confirm'
                                : 'warehouse-suggestions-deprecate-confirm'
                        }
                    >
                        {deleteView ? 'Delete view' : 'Mark deprecated'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
