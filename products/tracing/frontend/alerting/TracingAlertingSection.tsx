import { useActions, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { TracingAlertCreateModal } from './TracingAlertCreateModal'
import { TracingAlertEditModal } from './TracingAlertEditModal'
import { tracingAlertingLogic } from './tracingAlertingLogic'
import { TracingAlertList } from './TracingAlertList'

export function TracingAlertingSection(): JSX.Element {
    const { isCreateAlertModalOpen, editingAlert } = useValues(tracingAlertingLogic)
    const { closeCreateAlertModal, closeEditAlertModal } = useActions(tracingAlertingLogic)

    return (
        <>
            <LemonBanner type="info" dismissKey="tracing-alerts-beta-banner" className="mb-3">
                Tracing alerting is in beta. Alerts are checked every 5 minutes. Read the{' '}
                <Link to="https://posthog.com/docs/tracing" target="_blank">
                    docs
                </Link>{' '}
                or share feedback with what you'd like to see.
            </LemonBanner>
            <TracingAlertList />
            <TracingAlertCreateModal isOpen={isCreateAlertModalOpen} onClose={closeCreateAlertModal} />
            <TracingAlertEditModal alert={editingAlert} onClose={closeEditAlertModal} />
        </>
    )
}
