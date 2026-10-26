import { LemonDialog } from '@posthog/lemon-ui'

export function openDeleteLogsAlertDialog({
    alertName,
    deleteAlert,
}: {
    alertName: string | undefined
    deleteAlert: () => void
}): void {
    LemonDialog.open({
        title: `Delete "${alertName}"?`,
        description: 'This alert will be permanently deleted. This action cannot be undone.',
        primaryButton: {
            children: 'Delete',
            type: 'primary',
            status: 'danger',
            onClick: deleteAlert,
            'data-attr': 'logs-alert-delete-confirm',
        },
        secondaryButton: { children: 'Cancel' },
    })
}
