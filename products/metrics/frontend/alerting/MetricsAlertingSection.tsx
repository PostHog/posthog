import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { MetricsAlertCreateModal } from './MetricsAlertCreateModal'
import { MetricsAlertEditModal } from './MetricsAlertEditModal'
import { metricsAlertingLogic } from './metricsAlertingLogic'
import { MetricsAlertList } from './MetricsAlertList'

export function MetricsAlertingSection(): JSX.Element {
    return (
        <BindLogic logic={metricsAlertingLogic} props={{}}>
            <MetricsAlertingSectionContent />
        </BindLogic>
    )
}

function MetricsAlertingSectionContent(): JSX.Element {
    const { isCreateAlertModalOpen, editingAlert } = useValues(metricsAlertingLogic)
    const { closeCreateAlertModal, closeEditAlertModal } = useActions(metricsAlertingLogic)

    return (
        <>
            <LemonBanner type="info" dismissKey="metrics-alerts-beta-banner" className="mb-3">
                Metrics alerting is in beta. Each alert runs a PromQL query every minute and checks each series it
                returns.
            </LemonBanner>
            <MetricsAlertList />
            <MetricsAlertCreateModal isOpen={isCreateAlertModalOpen} onClose={closeCreateAlertModal} />
            <MetricsAlertEditModal alert={editingAlert} onClose={closeEditAlertModal} />
        </>
    )
}
