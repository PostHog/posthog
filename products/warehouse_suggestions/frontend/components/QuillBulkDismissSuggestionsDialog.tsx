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
import { countOf } from '../suggestionCopy'
import { warehouseSuggestionsSectionLogic } from '../warehouseSuggestionsSectionLogic'
import { QuillChoiceGroup } from './QuillChoiceGroup'
import { QuillDismissNoteField } from './QuillDismissNoteField'

const REASON_CHOICES = dismissReasonChoices('warehouse-suggestions-bulk-dismiss', { includeNotNow: true })

export function QuillBulkDismissSuggestionsDialog(): JSX.Element {
    const { bulkDismissOpen, selectedSuggestions, dismissReason, dismissNote } = useValues(
        warehouseSuggestionsSectionLogic
    )
    const { closeBulkDismiss, setDismissReason, setDismissNote, confirmBulkDismiss } = useActions(
        warehouseSuggestionsSectionLogic
    )
    const count = countOf(selectedSuggestions.length, 'suggestion', 'suggestions')

    return (
        <Dialog open={bulkDismissOpen} onOpenChange={(open: boolean) => !open && closeBulkDismiss()}>
            <DialogContent className="max-w-lg" data-attr="warehouse-suggestions-bulk-dismiss-dialog">
                <DialogHeader>
                    <DialogTitle>{`Dismiss ${count}?`}</DialogTitle>
                    <DialogDescription>Unless you pick Not now, they won't be suggested again.</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <QuillChoiceGroup<WarehouseSuggestionDismissalReasonEnumApi>
                            legend={DISMISS_REASON_LEGEND}
                            idPrefix="bulk-dismiss-reason"
                            value={dismissReason}
                            onChange={setDismissReason}
                            choices={REASON_CHOICES}
                            disabled={false}
                        />
                        <QuillDismissNoteField
                            id="bulk-dismiss-note"
                            value={dismissNote}
                            onChange={setDismissNote}
                            dataAttr="warehouse-suggestions-bulk-dismiss-note"
                        />
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeBulkDismiss}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => confirmBulkDismiss()}
                        data-attr="warehouse-suggestions-bulk-dismiss-confirm"
                    >
                        {`Dismiss ${count}`}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
