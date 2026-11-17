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

import { DISMISS_REASON_LEGEND, dismissReasonChoices } from '../dismissReasons'
import type { WarehouseSuggestionDismissalReasonEnumApi } from '../generated/api.schemas'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { QuillChoiceGroup } from './QuillChoiceGroup'
import { QuillDismissNoteField } from './QuillDismissNoteField'

const REASON_CHOICES = dismissReasonChoices('warehouse-suggestions-dismiss-reason', { includeNotNow: false })

export function QuillDismissSuggestionDialog(): JSX.Element | null {
    const { dismissDialogSuggestion, dismissReason, dismissNote, actionsInFlight } =
        useValues(warehouseSuggestionsLogic)
    const { closeDismissDialog, setDismissReason, setDismissNote, confirmDismiss } =
        useActions(warehouseSuggestionsLogic)

    if (!dismissDialogSuggestion) {
        return null
    }
    const inFlight = !!actionsInFlight[dismissDialogSuggestion.id]

    return (
        <Dialog open onOpenChange={(open: boolean) => !open && !inFlight && closeDismissDialog()}>
            <DialogContent
                className="max-w-lg"
                showCloseButton={!inFlight}
                data-attr="warehouse-suggestions-dismiss-dialog"
            >
                <DialogHeader>
                    <DialogTitle>{`Dismiss the suggestion for ${dismissDialogSuggestion.payload.subject_name}?`}</DialogTitle>
                    <DialogDescription>It won't be suggested again.</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <QuillChoiceGroup<WarehouseSuggestionDismissalReasonEnumApi>
                            legend={DISMISS_REASON_LEGEND}
                            idPrefix="dismiss-reason"
                            value={dismissReason}
                            onChange={setDismissReason}
                            choices={REASON_CHOICES}
                            disabled={inFlight}
                        />
                        <QuillDismissNoteField
                            id="dismiss-note"
                            value={dismissNote}
                            onChange={setDismissNote}
                            dataAttr="warehouse-suggestions-dismiss-note"
                        />
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeDismissDialog}
                        disabledReason={inFlight ? 'Working' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={inFlight}
                        onClick={() => confirmDismiss()}
                        data-attr="warehouse-suggestions-dismiss-confirm"
                    >
                        Dismiss
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
