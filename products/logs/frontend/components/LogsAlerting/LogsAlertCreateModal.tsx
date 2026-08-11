import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconTestTube } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { AlertEditorFormDetails } from 'products/alerts/frontend/components/AlertEditor'
import { AlertWizard, AlertWizardStep } from 'products/alerts/frontend/components/AlertWizard'

import { LogsAlertFilters, LogsAlertTrigger } from './LogsAlertForm'
import { logsAlertFormLogic, LogsAlertFormType } from './logsAlertFormLogic'
import { logsAlertNotificationLogic } from './logsAlertNotificationLogic'
import { LogsAlertNotifications } from './LogsAlertNotifications'
import { LogsAlertSimulation } from './LogsAlertSimulation'
import { hasAnyFilter, PendingLogsAlertNotification } from './logsAlertUtils'

interface LogsAlertCreateModalProps {
    isOpen: boolean
    onClose: () => void
}

export function LogsAlertCreateModal({ isOpen, onClose }: LogsAlertCreateModalProps): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="" simple width={900}>
            {isOpen ? <LogsAlertCreateModalContent onClose={onClose} /> : null}
        </LemonModal>
    )
}

function LogsAlertCreateModalContent({ onClose }: { onClose: () => void }): JSX.Element {
    const formLogicProps = { alert: null, onCreateSuccess: onClose }
    const { isAlertFormSubmitting, alertFormChanged, alertForm, isSimulationPanelOpen } = useValues(
        logsAlertFormLogic(formLogicProps)
    )
    const { openSimulationPanel, closeSimulationPanel, touchAlertFormField } = useActions(
        logsAlertFormLogic(formLogicProps)
    )
    const { pendingNotifications } = useValues(logsAlertNotificationLogic({}))
    const hasLogFilter = hasAnyFilter(alertForm.severityLevels, alertForm.serviceNames, alertForm.filterGroup)
    const nameError = alertForm.name.trim() ? undefined : 'Enter an alert name.'
    const configurationCannotAdvanceReason = nameError ?? (!hasLogFilter ? 'Add at least one log filter.' : undefined)
    const steps = buildLogsAlertWizardSteps({ alertForm, pendingNotifications, configurationCannotAdvanceReason })

    return (
        <BindLogic logic={logsAlertFormLogic} props={formLogicProps}>
            <BindLogic logic={logsAlertNotificationLogic} props={{}}>
                <Form
                    logic={logsAlertFormLogic}
                    props={formLogicProps}
                    formKey="alertForm"
                    enableFormOnSubmit
                    className="LemonModal__layout"
                >
                    <AlertWizard
                        title="New alert"
                        steps={steps}
                        isSubmitting={isAlertFormSubmitting}
                        hasChanges={alertFormChanged}
                        onBack={onClose}
                        onSubmitAttempted={() => touchAlertFormField('name')}
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
                    />
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

function buildLogsAlertWizardSteps({
    alertForm,
    pendingNotifications,
    configurationCannotAdvanceReason,
}: {
    alertForm: LogsAlertFormType
    pendingNotifications: PendingLogsAlertNotification[]
    configurationCannotAdvanceReason: string | undefined
}): AlertWizardStep[] {
    return [
        {
            key: 'configure',
            title: 'Configure alert',
            description: 'Select matching logs and set when this alert fires.',
            canAdvance: !configurationCannotAdvanceReason,
            cannotAdvanceReason: configurationCannotAdvanceReason,
            content: (
                <div className="max-w-2xl space-y-6">
                    <AlertEditorFormDetails nameError={configurationCannotAdvanceReason} />
                    <LogsAlertFilters />
                    <LogsAlertTrigger />
                </div>
            ),
        },
        {
            key: 'notify',
            title: 'Notify',
            description: 'Choose where to send alert events.',
            content: (
                <div className="max-w-2xl">
                    <LogsAlertNotifications />
                </div>
            ),
        },
        {
            key: 'review',
            title: 'Review',
            description: 'Confirm the alert before you create it.',
            content: <LogsAlertReview alertForm={alertForm} pendingNotifications={pendingNotifications} />,
        },
    ]
}

function LogsAlertReview({
    alertForm,
    pendingNotifications,
}: {
    alertForm: LogsAlertFormType
    pendingNotifications: PendingLogsAlertNotification[]
}): JSX.Element {
    const severity = alertForm.severityLevels.length ? alertForm.severityLevels.join(', ') : 'all severities'
    const services = alertForm.serviceNames.length ? alertForm.serviceNames.join(', ') : 'all services'
    const attributeCount = alertForm.filterGroup.values.length
    const notificationSummary = pendingNotifications.length
        ? `${pendingNotifications.length} notification destination${pendingNotifications.length === 1 ? '' : 's'}`
        : 'No notification destinations'

    return (
        <div className="max-w-2xl space-y-4">
            {pendingNotifications.length === 0 ? (
                <LemonBanner type="warning">
                    This alert will run without notifications. Go back to Notify to add a destination.
                </LemonBanner>
            ) : null}
            <div className="space-y-1.5 rounded border border-border bg-bg-light p-3 text-sm">
                <ReviewItem label="Name" value={alertForm.name} />
                <ReviewItem label="Severity" value={severity} />
                <ReviewItem label="Service" value={services} />
                <ReviewItem
                    label="Attributes"
                    value={
                        attributeCount ? `${attributeCount} attribute filter${attributeCount === 1 ? '' : 's'}` : 'None'
                    }
                />
                <ReviewItem
                    label="Fires when"
                    value={`log count is ${alertForm.thresholdOperator} ${alertForm.thresholdCount} in ${alertForm.windowMinutes} minutes`}
                />
                <ReviewItem
                    label="Noise reduction"
                    value={`${alertForm.datapointsToAlarm} of ${alertForm.evaluationPeriods} checks must match`}
                />
                <ReviewItem label="Notification cooldown" value={`${alertForm.cooldownMinutes} minutes`} />
                <ReviewItem label="Notifies" value={notificationSummary} />
            </div>
        </div>
    )
}

function ReviewItem({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex gap-2">
            <span className="w-36 shrink-0 text-muted">{label}</span>
            <span className="font-medium">{value}</span>
        </div>
    )
}
