import { LemonDialog } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

export function confirmBulkDeleteSymbolSets(count: number, onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Delete symbol sets',
        description: `Are you sure you want to delete ${pluralize(count, 'symbol set', 'symbol sets')}?`,
        secondaryButton: {
            type: 'secondary',
            children: 'Cancel',
        },
        primaryButton: {
            type: 'primary',
            status: 'danger',
            onClick: onConfirm,
            children: 'Delete',
        },
    })
}

export function confirmDeleteSymbolSet(onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Delete symbol set',
        description: 'Are you sure you want to delete this symbol set?',
        secondaryButton: {
            type: 'secondary',
            children: 'Cancel',
        },
        primaryButton: {
            type: 'primary',
            onClick: onConfirm,
            children: 'Delete',
        },
    })
}
