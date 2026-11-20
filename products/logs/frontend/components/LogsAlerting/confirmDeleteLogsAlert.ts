import { LemonDialog } from '@posthog/lemon-ui'

import { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

export function confirmDeleteLogsAlert(alert: LogsAlertConfigurationApi, deleteAlert: (alertId: string) => void): void {
    LemonDialog.open({
        title: `Delete "${alert.name}"?`,
        description: 'This alert will be permanently deleted. This action cannot be undone.',
        primaryButton: {
            children: 'Delete',
            type: 'primary',
            status: 'danger',
            onClick: () => deleteAlert(alert.id),
            'data-attr': 'logs-alert-delete-confirm',
        },
        secondaryButton: { children: 'Cancel' },
    })
}
