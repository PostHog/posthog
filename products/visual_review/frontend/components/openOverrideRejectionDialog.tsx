import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

export interface OverrideRejectionDialogProps {
    title: string
    /** The rejecter's reason, quoted so the reader sees what they replace. */
    reason: string
    description: string
    confirmLabel: string
    dataAttr: string
    onConfirm: () => void
}

/** Confirms replacing or undoing someone else's rejection. */
export function openOverrideRejectionDialog({
    title,
    reason,
    description,
    confirmLabel,
    dataAttr,
    onConfirm,
}: OverrideRejectionDialogProps): void {
    // A dialog stays clickable during its close transition, so a double click would send the call twice.
    let submitted = false
    LemonDialog.open({
        title,
        description: (
            <div className="flex flex-col gap-2">
                <blockquote className="m-0 border-l-2 border-danger pl-2 break-words">{reason}</blockquote>
                <p className="m-0">{description}</p>
            </div>
        ),
        primaryButton: {
            children: confirmLabel,
            onClick: () => {
                if (!submitted) {
                    submitted = true
                    onConfirm()
                }
            },
            'data-attr': dataAttr,
        },
        secondaryButton: { children: 'Cancel' },
    })
}
