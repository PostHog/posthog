import { useActions, useValues } from 'kea'

import { Button, Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@posthog/quill'

import type { WarehouseSuggestionDismissalReasonEnumApi } from '../generated/api.schemas'
import { countOf } from '../suggestionCopy'
import { warehouseSuggestionsSectionLogic } from '../warehouseSuggestionsSectionLogic'
import { QuillChoice, QuillChoiceGroup } from './QuillChoiceGroup'

const REASON_CHOICES: QuillChoice<WarehouseSuggestionDismissalReasonEnumApi>[] = [
    {
        value: 'not_now',
        label: 'Not now',
        description: 'Each one can be suggested again if the case for it grows a lot.',
        'data-attr': 'warehouse-suggestions-bulk-dismiss-not-now',
    },
    {
        value: 'not_useful',
        label: 'Not useful',
        description: "They won't be suggested again.",
        'data-attr': 'warehouse-suggestions-bulk-dismiss-not-useful',
    },
    {
        value: 'other',
        label: 'Another reason',
        description: "They won't be suggested again.",
        'data-attr': 'warehouse-suggestions-bulk-dismiss-other',
    },
]

export function QuillBulkDismissSuggestionsDialog(): JSX.Element {
    const { bulkDismissOpen, selectedSuggestions, dismissReason } = useValues(warehouseSuggestionsSectionLogic)
    const { closeBulkDismiss, setDismissReason, confirmBulkDismiss } = useActions(warehouseSuggestionsSectionLogic)
    const count = countOf(selectedSuggestions.length, 'suggestion', 'suggestions')

    return (
        <Dialog open={bulkDismissOpen} onOpenChange={(open: boolean) => !open && closeBulkDismiss()}>
            <DialogContent className="max-w-lg" data-attr="warehouse-suggestions-bulk-dismiss-dialog">
                <DialogHeader>
                    <DialogTitle>{`Dismiss ${count}?`}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <QuillChoiceGroup<WarehouseSuggestionDismissalReasonEnumApi>
                        legend="Why"
                        idPrefix="bulk-dismiss-reason"
                        value={dismissReason}
                        onChange={setDismissReason}
                        choices={REASON_CHOICES}
                        disabled={false}
                    />
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
