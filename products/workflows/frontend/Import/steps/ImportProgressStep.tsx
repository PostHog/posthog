import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { CustomerIOImportRunProgress } from '../components/CustomerIOImportRunProgress'
import { ImportRunResult } from '../components/ImportRunResult'
import { ImportStepFooter } from '../components/ImportStepFooter'
import { LegacyImportResult } from '../components/LegacyImportResult'
import { PreferencesCsvUpload } from '../components/PreferencesCsvUpload'
import { customerIOImportLogic } from '../customerIOImportLogic'

export function ImportProgressStep(): JSX.Element {
    const { latestImportRun, isImportRunActive, syncConfig } = useValues(customerIOImportLogic)
    const { setStep } = useActions(customerIOImportLogic)

    if (latestImportRun && isImportRunActive) {
        return (
            <div className="space-y-4">
                <LemonBanner type="info">
                    The import runs in the background. You can leave this page and come back to check on it.
                </LemonBanner>
                <CustomerIOImportRunProgress run={latestImportRun} />
            </div>
        )
    }

    const hasImported = !!latestImportRun || syncConfig?.app_import_result?.status === 'completed'

    return (
        <div className="space-y-4">
            {latestImportRun ? (
                <ImportRunResult run={latestImportRun} />
            ) : hasImported ? (
                <LegacyImportResult />
            ) : (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Choose what to import',
                        onClick: () => setStep('choose'),
                        'data-attr': 'messaging-import-empty-choose',
                    }}
                >
                    You haven't imported anything yet.
                </LemonBanner>
            )}
            {hasImported && (
                <div className="space-y-2 border-t pt-4">
                    <h3 className="text-base font-semibold m-0">Subscription preferences (optional)</h3>
                    <PreferencesCsvUpload />
                </div>
            )}
            <ImportStepFooter>
                {hasImported && (
                    <LemonButton
                        type="secondary"
                        onClick={() => setStep('choose')}
                        data-attr="customerio-import-run-again"
                    >
                        Run again
                    </LemonButton>
                )}
                <LemonButton type="primary" onClick={() => setStep('sync')} data-attr="messaging-import-progress-next">
                    Next
                </LemonButton>
            </ImportStepFooter>
        </div>
    )
}
