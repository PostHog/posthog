import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

import { logsAlertFormLogic } from './logsAlertFormLogic'

export function QuillLogsAlertRegroupConfirmModal(): JSX.Element {
    const { isRegroupConfirmationOpen, regroupConfirmation } = useValues(logsAlertFormLogic)
    const { closeRegroupConfirmation, confirmRegroup } = useActions(logsAlertFormLogic)

    return (
        <AlertDialog
            open={isRegroupConfirmationOpen}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    closeRegroupConfirmation()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Change how this alert groups?</AlertDialogTitle>
                    <AlertDialogDescription>{regroupConfirmation}</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={closeRegroupConfirmation}>
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        onClick={confirmRegroup}
                        data-attr="logs-alert-regroup-confirm"
                    >
                        Save and reset
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
