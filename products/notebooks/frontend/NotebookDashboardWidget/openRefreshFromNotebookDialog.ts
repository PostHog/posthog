import { LemonDialog } from '@posthog/lemon-ui'

export const NOTEBOOK_WIDGET_NO_SNAPSHOT_REASON = 'Load the saved results first'

export function openRefreshFromNotebookDialog(onRun: () => void): void {
    LemonDialog.open({
        title: 'Refresh from notebook?',
        description:
            'This runs all saved data cells using the notebook’s variables. Python compute may incur charges. Dashboard filters do not change these results.',
        primaryButton: { children: 'Run notebook', onClick: onRun },
        secondaryButton: { children: 'Cancel' },
    })
}
