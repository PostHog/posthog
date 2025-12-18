import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

export function openDeletePromptDialog(onDelete: () => void): void {
    LemonDialog.open({
        title: 'Delete prompt?',
        description:
            'This action cannot be undone. If you have any code currently fetching this prompt, it will no longer be able to retrieve it.',
        primaryButton: {
            children: 'Delete',
            type: 'primary',
            status: 'danger',
            onClick: onDelete,
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'secondary',
        },
    })
}
