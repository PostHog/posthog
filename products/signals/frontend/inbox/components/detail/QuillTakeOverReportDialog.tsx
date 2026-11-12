import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

import { fullNameOrEmail } from 'lib/utils/strings'

import type { _UserApi } from 'products/signals/frontend/generated/api.schemas'

/** Asks before the user takes over a teammate's claim, because the server tells that person their work moved. */
export function QuillTakeOverReportDialog({
    holder,
    holderIsAgent,
    onClose,
}: {
    holder: _UserApi
    holderIsAgent: boolean
    /** Runs on every close. `confirmed` is false for Cancel, Escape and a click outside. */
    onClose: (confirmed: boolean) => void
}): JSX.Element {
    const holderName = fullNameOrEmail(holder)
    return (
        <AlertDialog
            open
            onOpenChange={(open: boolean) => {
                if (!open) {
                    onClose(false)
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Take over this report?</AlertDialogTitle>
                    <AlertDialogDescription>
                        {`${holderIsAgent ? `${holderName}'s agent` : holderName} is working on this report. If you take it over, we let ${holderName} know.`}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={() => onClose(false)}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={() => onClose(true)} data-attr="inbox-report-takeover-confirm">
                        Take over
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
