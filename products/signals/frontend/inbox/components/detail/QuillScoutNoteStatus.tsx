import { useState } from 'react'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Badge,
    Button,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

export function QuillScoutNoteStatus({
    active,
    retireDisabledReason,
    onRetire,
}: {
    active: boolean
    retireDisabledReason?: string
    onRetire: () => void
}): JSX.Element {
    const [confirming, setConfirming] = useState(false)

    if (!active) {
        return (
            <Tooltip>
                <TooltipTrigger render={<Badge />}>Inactive</TooltipTrigger>
                <TooltipContent>Retired or expired. Scouts no longer read it.</TooltipContent>
            </Tooltip>
        )
    }
    return (
        <>
            <Badge variant="success">Active</Badge>
            <Button
                size="xs"
                variant="link-muted"
                disabledReason={retireDisabledReason}
                onClick={() => setConfirming(true)}
                data-attr="inbox-report-note-retire"
            >
                Retire
            </Button>
            {confirming && (
                <AlertDialog
                    open
                    onOpenChange={(open: boolean) => {
                        if (!open) {
                            setConfirming(false)
                        }
                    }}
                >
                    <AlertDialogContent>
                        <AlertDialogHeader>
                            <AlertDialogTitle>Retire this note?</AlertDialogTitle>
                            <AlertDialogDescription>
                                Scouts stop reading it from their next run onward. It stays on the report.
                            </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                            <Button variant="outline" onClick={() => setConfirming(false)}>
                                Cancel
                            </Button>
                            <Button
                                variant="destructive-outline"
                                onClick={() => {
                                    setConfirming(false)
                                    onRetire()
                                }}
                            >
                                Retire
                            </Button>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                </AlertDialog>
            )}
        </>
    )
}
