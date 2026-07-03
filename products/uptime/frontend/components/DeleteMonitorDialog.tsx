import { useRef } from 'react'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill-primitives'

interface DeleteMonitorDialogProps {
    /** Name of the monitor pending deletion; null keeps the dialog closed. */
    monitorName: string | null
    deleting: boolean
    onConfirm: () => void
    onCancel: () => void
}

export function DeleteMonitorDialog({
    monitorName,
    deleting,
    onConfirm,
    onCancel,
}: DeleteMonitorDialogProps): JSX.Element {
    // Keep the last shown name so the title doesn't blank out during the close transition.
    const lastNameRef = useRef('')
    if (monitorName !== null) {
        lastNameRef.current = monitorName
    }

    return (
        <AlertDialog
            open={monitorName !== null}
            onOpenChange={(open) => {
                if (!open && !deleting) {
                    onCancel()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Delete monitor "{lastNameRef.current}"?</AlertDialogTitle>
                    <AlertDialogDescription>
                        Historical pings stay in the audit log; the monitor disappears from the list.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" disabled={deleting} />}>
                        Cancel
                    </AlertDialogClose>
                    <Button variant="destructive" loading={deleting} onClick={onConfirm}>
                        Delete monitor
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
