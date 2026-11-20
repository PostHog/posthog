import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { LogsAlertCreateModal } from './LogsAlertCreateModal'
import { LogsAlertEditModal } from './LogsAlertEditModal'
import { logsAlertingLogic } from './logsAlertingLogic'
import { LogsAlertList } from './LogsAlertList'
import { QuillLogsAlertCreateModal } from './QuillLogsAlertCreateModal'
import { QuillLogsAlertEditModal } from './QuillLogsAlertEditModal'
import { QuillLogsAlertList } from './QuillLogsAlertList'
import { QuillLogsAlertsBetaBanner } from './QuillLogsAlertsBetaBanner'

const BETA_BANNER_DISMISS_KEY = 'logs-alerts-beta-banner'

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
    const todayRailNav = useQuillSurface()

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-3">
                <QuillLogsAlertsBetaBanner dismissKey={BETA_BANNER_DISMISS_KEY} />
                <QuillLogsAlertList />
                <QuillLogsAlertCreateModal isOpen={isCreateAlertModalOpen} onClose={closeCreateAlertModal} />
                <QuillLogsAlertEditModal alert={editingAlert} onClose={closeEditAlertModal} />
            </div>
        )
    }

    return (
        <>
            <LemonBanner
                type="info"
                dismissKey={BETA_BANNER_DISMISS_KEY}
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
