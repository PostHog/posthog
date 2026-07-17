import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconTestTube } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { AlertEditor, AlertEditorFormDetails } from 'products/alerts/frontend/components/AlertEditor'
import {
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { LogsAlertEventHistoryModal } from './LogsAlertEventHistory'
import { LogsAlertForm } from './LogsAlertForm'
import { logsAlertFormLogic } from './logsAlertFormLogic'
import { logsAlertingLogic } from './logsAlertingLogic'
import { LogsAlertList } from './LogsAlertList'
import { logsAlertNotificationLogic } from './logsAlertNotificationLogic'
import { LogsAlertSimulation } from './LogsAlertSimulation'

export function LogsAlertingSection(): JSX.Element {
    return (
        <BindLogic logic={logsAlertingLogic} props={{}}>
            <LogsAlertingSectionInner />
        </BindLogic>
    )
}

function LogsAlertingSectionInner(): JSX.Element {
    const { isCreating, editingAlert, viewingHistoryAlert } = useValues(logsAlertingLogic)
    const { setIsCreating, setEditingAlert, setViewingHistoryAlert } = useActions(logsAlertingLogic)

    const isModalOpen = isCreating || editingAlert !== null

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
            <LemonModal
                isOpen={isModalOpen}
                onClose={() => {
                    setIsCreating(false)
                    setEditingAlert(null)
                }}
                title=""
                simple
                width={720}
            >
                {isModalOpen ? <LogsAlertModalContent editingAlert={editingAlert} /> : null}
            </LemonModal>
            <LogsAlertEventHistoryModal alert={viewingHistoryAlert} onClose={() => setViewingHistoryAlert(null)} />
        </>
    )
}

function LogsAlertModalContent({ editingAlert }: { editingAlert: LogsAlertConfigurationApi | null }): JSX.Element {
    const notifLogicProps = { alertId: editingAlert?.id }
    const formLogicProps = { alert: editingAlert }
    const { isAlertFormSubmitting, alertFormChanged, isSimulationPanelOpen } = useValues(
        logsAlertFormLogic(formLogicProps)
    )
    const { openSimulationPanel, closeSimulationPanel } = useActions(logsAlertFormLogic(formLogicProps))
    const { resetAlert } = useActions(logsAlertingLogic)
    const { resettingAlertIds } = useValues(logsAlertingLogic)
    const { pendingNotifications } = useValues(logsAlertNotificationLogic(notifLogicProps))
    const hasPendingNotifications = pendingNotifications.length > 0
    const isBroken = editingAlert?.state === LogsAlertConfigurationStateEnumApi.Broken
    const isResetting = editingAlert ? resettingAlertIds.has(editingAlert.id) : false

    return (
        <BindLogic logic={logsAlertFormLogic} props={formLogicProps}>
            <BindLogic logic={logsAlertNotificationLogic} props={notifLogicProps}>
                <Form
                    logic={logsAlertFormLogic}
                    props={formLogicProps}
                    formKey="alertForm"
                    enableFormOnSubmit
                    className="LemonModal__layout"
                >
                    <AlertEditor
                        title={editingAlert ? 'Edit alert' : 'New alert'}
                        description="Alerts are checked every 5 minutes."
                        isEditing={editingAlert !== null}
                        isSubmitting={isAlertFormSubmitting}
                        hasChanges={alertFormChanged}
                        hasPendingChanges={hasPendingNotifications}
                        leadingActions={
                            <LemonButton
                                type="secondary"
                                icon={<IconTestTube />}
                                onClick={openSimulationPanel}
                                tooltip="Run this alert against historical data to see when it would have fired"
                            >
                                Simulate
                            </LemonButton>
                        }
                    >
                        {isBroken && editingAlert ? (
                            <LemonBanner
                                type="error"
                                className="mb-3"
                                action={{
                                    children: isResetting ? 'Resetting…' : 'Reset alert',
                                    onClick: () => resetAlert(editingAlert.id),
                                    loading: isResetting,
                                    disabledReason: isResetting ? 'Reset in progress' : undefined,
                                }}
                            >
                                <div className="font-semibold">
                                    This alert was auto-disabled after repeated check failures.
                                </div>
                                {editingAlert.last_error_message ? (
                                    <div className="text-xs text-muted-alt mt-1">
                                        Last error: {editingAlert.last_error_message}
                                    </div>
                                ) : null}
                            </LemonBanner>
                        ) : null}
                        <div className="space-y-6 max-w-2xl">
                            <AlertEditorFormDetails />
                            <LogsAlertForm />
                        </div>
                    </AlertEditor>
                </Form>

                <LemonModal
                    isOpen={isSimulationPanelOpen}
                    onClose={closeSimulationPanel}
                    title="Alert simulation"
                    description="Run the alert against historical data to preview when it would have fired. Includes threshold evaluation, N-of-M noise reduction, and cooldown."
                    width={960}
                >
                    <LogsAlertSimulation />
                </LemonModal>
            </BindLogic>
        </BindLogic>
    )
}
