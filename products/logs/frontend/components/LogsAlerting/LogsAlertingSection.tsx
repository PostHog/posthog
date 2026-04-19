import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconTestTube } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import {
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

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
    const { isCreating, editingAlert } = useValues(logsAlertingLogic)
    const { setIsCreating, setEditingAlert } = useActions(logsAlertingLogic)

    const isModalOpen = isCreating || editingAlert !== null

    return (
        <>
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
                {isModalOpen && <LogsAlertModalContent editingAlert={editingAlert} />}
            </LemonModal>
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
                    <LemonModal.Header>
                        <h3>{editingAlert ? 'Edit alert' : 'New alert'}</h3>
                        <p className="text-muted text-sm m-0">Alerts are checked every minute.</p>
                    </LemonModal.Header>
                    <LemonModal.Content>
                        {isBroken && editingAlert && (
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
                                {editingAlert.last_error_message && (
                                    <div className="text-xs text-muted-alt mt-1">
                                        Last error: {editingAlert.last_error_message}
                                    </div>
                                )}
                            </LemonBanner>
                        )}
                        <LogsAlertForm />
                    </LemonModal.Content>
                    <LemonModal.Footer>
                        <LemonButton
                            type="secondary"
                            icon={<IconTestTube />}
                            onClick={openSimulationPanel}
                            tooltip="Run this alert against historical data to see when it would have fired"
                        >
                            Simulate
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isAlertFormSubmitting}
                            disabledReason={
                                editingAlert && !alertFormChanged && !hasPendingNotifications
                                    ? 'No changes to save'
                                    : undefined
                            }
                        >
                            {editingAlert ? 'Save' : 'Create alert'}
                        </LemonButton>
                    </LemonModal.Footer>
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
