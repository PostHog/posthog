import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

export function openEarlyAccessFeatureDeleteDialog(featureName: string, onDelete: () => void): void {
    LemonDialog.open({
        title: 'Permanently delete feature?',
        description: `Deleting "${featureName || 'this feature'}" also removes the opt in conditions from its feature flag.`,
        primaryButton: {
            children: 'Delete',
            type: 'primary',
            status: 'danger',
            'data-attr': 'confirm-delete-feature',
            onClick: onDelete,
        },
        secondaryButton: {
            children: 'Close',
            type: 'secondary',
        },
    })
}
