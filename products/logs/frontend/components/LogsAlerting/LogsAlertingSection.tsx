import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { LogsAlertCreateModal } from './LogsAlertCreateModal'
import { LogsAlertEditModal } from './LogsAlertEditModal'
import { logsAlertingLogic } from './logsAlertingLogic'
import { LogsAlertList } from './LogsAlertList'

export function LogsAlertingSection(): JSX.Element {
    return (
        <BindLogic logic={logsAlertingLogic} props={{}}>
            <LogsAlertingSectionContent />
        </BindLogic>
    )
}

function LogsAlertingSectionContent(): JSX.Element {
    const { isCreateAlertModalOpen, editingAlert } = useValues(logsAlertingLogic)
    const { closeCreateAlertModal, closeEditAlertModal } = useActions(logsAlertingLogic)

    return (
        <>
            <LemonBanner
                type="info"
                dismissKey="logs-alerts-beta-banner"
                className="mb-3"
                action={{ children: 'Send feedback', id: 'logs-alerts-feedback-button' }}
            >
                Logs alerting is in beta. Alerts are checked every 5 minutes. Read the{' '}
                <Link to="https://posthog.com/docs/logs/alerts" target="_blank">
                    docs
                </Link>{' '}
                or share feedback with what you'd like to see.
            </LemonBanner>
            <LogsAlertList />
            <LogsAlertCreateModal isOpen={isCreateAlertModalOpen} onClose={closeCreateAlertModal} />
            <LogsAlertEditModal alert={editingAlert} onClose={closeEditAlertModal} />
        </>
    )
}
