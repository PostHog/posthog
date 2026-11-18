import { type ReactNode } from 'react'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

/** A quill confirmation, the twin of a two-button LemonDialog. */
export function QuillConfirmDialog({
    open,
    onOpenChange,
    title,
    description,
    confirmLabel,
    destructive = false,
    onConfirm,
    cancelLabel = 'Cancel',
    dataAttr,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    title: string
    description: ReactNode
    confirmLabel: string
    destructive?: boolean
    onConfirm: () => void
    cancelLabel?: string
    dataAttr?: string
}): JSX.Element {
    return (
        <AlertDialog open={open} onOpenChange={onOpenChange}>
            <AlertDialogContent data-attr={dataAttr}>
                <AlertDialogHeader>
                    <AlertDialogTitle>{title}</AlertDialogTitle>
                    <AlertDialogDescription render={<div />}>{description}</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>{cancelLabel}</AlertDialogClose>
                    <AlertDialogClose
                        render={<Button variant={destructive ? 'destructive' : 'primary'} onClick={onConfirm} />}
                    >
                        {confirmLabel}
                    </AlertDialogClose>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
