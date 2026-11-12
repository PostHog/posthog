import { LemonDialog } from '@posthog/lemon-ui'

import { PlatformAlertConfigurationApi } from 'products/alerts_platform/frontend/generated/api.schemas'

export function confirmDeleteTracesAlert(alert: PlatformAlertConfigurationApi, onConfirm: () => void): void {
    LemonDialog.open({
        title: `Delete "${alert.name}"?`,
        description: 'This permanently deletes the alert and its destinations. You cannot undo it.',
        primaryButton: {
            children: 'Delete',
            type: 'primary',
            status: 'danger',
            onClick: onConfirm,
            'data-attr': 'traces-alert-delete-confirm',
        },
        secondaryButton: { children: 'Cancel' },
    })
}
