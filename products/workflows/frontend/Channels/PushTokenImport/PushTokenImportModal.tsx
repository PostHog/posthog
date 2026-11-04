import { useActions, useValues } from 'kea'

import { LemonModal, Spinner } from '@posthog/lemon-ui'

import { getIntegrationNameFromKind } from 'lib/integrations/utils'

import { PushTokenImportFooter } from './PushTokenImportFooter'
import { PushTokenImportForm } from './PushTokenImportForm'
import { pushTokenImportLogic } from './pushTokenImportLogic'
import { PushTokenImportProgress } from './PushTokenImportProgress'
import { PushTokenImportResult } from './PushTokenImportResult'

/** Registers devices from a CSV export, for example from another push provider, on an APNs or Firebase channel. */
export function PushTokenImportModal(): JSX.Element {
    const { isOpen, integration, loadingLatest, currentImport, isRunning, submitting } = useValues(pushTokenImportLogic)
    const { closeImport } = useActions(pushTokenImportLogic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={submitting ? undefined : closeImport}
            title="Import devices"
            description={
                integration
                    ? `${getIntegrationNameFromKind(integration.kind)} channel: ${integration.display_name}`
                    : undefined
            }
            width={720}
            footer={<PushTokenImportFooter />}
        >
            {/* Distinct IDs and device tokens stay out of session recordings. */}
            <div className="flex flex-col gap-4 ph-no-capture ph-replay-block" data-attr="push-token-import-modal">
                {loadingLatest ? (
                    <Spinner />
                ) : isRunning ? (
                    <PushTokenImportProgress />
                ) : currentImport ? (
                    <PushTokenImportResult />
                ) : (
                    <PushTokenImportForm />
                )}
            </div>
        </LemonModal>
    )
}
