import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonModal } from '@posthog/lemon-ui'

import { WizardReview } from 'lib/components/WizardReview'

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
    const formLogicProps = { alert: null, onSubmitSuccess: onClose }
    const { isAlertFormSubmitting, alertFormChanged, alertForm } = useValues(logsAlertFormLogic(formLogicProps))
    const { touchAlertFormField } = useActions(logsAlertFormLogic(formLogicProps))
    const { pendingNotifications } = useValues(logsAlertNotificationLogic({}))
    const hasLogFilter = hasAnyFilter(alertForm.severityLevels, alertForm.serviceNames, alertForm.filterGroup)
    const nameError = alertForm.name.trim() ? undefined : 'Enter an alert name.'
    const filterError = hasLogFilter
        ? undefined
        : 'Select at least one severity or service, or add an attribute filter.'
    const configurationCannotAdvanceReason = nameError ?? filterError
    const steps = buildLogsAlertWizardSteps({
        alertForm,
        pendingNotifications,
        configurationCannotAdvanceReason,
        nameError,
        filterError,
    })

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
                    />
                </Form>
            </BindLogic>
        </BindLogic>
    )
}

function buildLogsAlertWizardSteps({
    alertForm,
    pendingNotifications,
    configurationCannotAdvanceReason,
    nameError,
    filterError,
}: {
    alertForm: LogsAlertFormType
    pendingNotifications: PendingLogsAlertNotification[]
    configurationCannotAdvanceReason: string | undefined
    nameError: string | undefined
    filterError: string | undefined
}): AlertWizardStep[] {
    return [
        {
            key: 'configure',
            title: 'Configure',
            description: 'Select matching logs and set when this alert fires.',
            canAdvance: !configurationCannotAdvanceReason,
            cannotAdvanceReason: configurationCannotAdvanceReason,
            renderContent: (showValidationErrors) => (
                <div className="max-w-2xl space-y-5">
                    <AlertEditorFormDetails nameError={showValidationErrors ? nameError : undefined} />
                    <LogsAlertFilters filterError={showValidationErrors ? filterError : undefined} />
                </div>
            ),
        },
        {
            key: 'trigger',
            title: 'Set trigger',
            description: 'Set the log count that fires the alert and reduce notification noise if needed.',
            content: (
                <div className="space-y-6">
                    <LogsAlertTrigger />
                    <LogsAlertSimulation embedded />
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
        <WizardReview
            notice={
                pendingNotifications.length === 0 ? (
                    <LemonBanner type="warning">
                        This alert will run without notifications. Go back to Notify to add a destination.
                    </LemonBanner>
                ) : undefined
            }
            items={[
                { label: 'Name', value: alertForm.name },
                { label: 'Severity', value: severity },
                { label: 'Service', value: services },
                {
                    label: 'Attributes',
                    value: attributeCount
                        ? `${attributeCount} attribute filter${attributeCount === 1 ? '' : 's'}`
                        : 'None',
                },
                {
                    label: 'Fires when',
                    value: `log count is ${alertForm.thresholdOperator} ${alertForm.thresholdCount} in ${alertForm.windowMinutes} minutes`,
                },
                {
                    label: 'Noise reduction',
                    value: `${alertForm.datapointsToAlarm} of ${alertForm.evaluationPeriods} checks must match`,
                },
                { label: 'Notification cooldown', value: `${alertForm.cooldownMinutes} minutes` },
                { label: 'Notifies', value: notificationSummary },
            ]}
        />
    )
}
