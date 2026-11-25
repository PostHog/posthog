import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { metricsDashboardImportLogic } from './metricsDashboardImportLogic'

export function DashboardImportFailedFooter(): JSX.Element {
    const { retrying, currentImport } = useValues(metricsDashboardImportLogic)
    const { closeImportModal, retryImport, dismissImport } = useActions(metricsDashboardImportLogic)

    return (
        <div className="flex flex-1 items-center justify-between gap-2">
            <LemonButton
                type="tertiary"
                onClick={() => currentImport && dismissImport(currentImport)}
                disabledReason={currentImport?.id ? undefined : 'This import is not saved'}
                data-attr="metrics-dashboard-import-dismiss"
            >
                Dismiss
            </LemonButton>
            <div className="flex gap-2">
                <LemonButton type="secondary" onClick={closeImportModal}>
                    Close
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={() => currentImport && retryImport(currentImport)}
                    loading={retrying}
                    data-attr="metrics-dashboard-import-retry"
                >
                    Try again
                </LemonButton>
            </div>
        </div>
    )
}
