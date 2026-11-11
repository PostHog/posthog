import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonModal } from '@posthog/lemon-ui'

import { WizardReview } from 'lib/components/WizardReview'

import { AlertWizard, AlertWizardStep } from 'products/alerts/frontend/components/AlertWizard'

import { metricsAlertFormLogic } from './metricsAlertFormLogic'
import { MetricsAlertNotifyFields } from './MetricsAlertNotifyFields'
import { MetricsAlertQueryFields } from './MetricsAlertQueryFields'
import { MetricsAlertTriggerFields } from './MetricsAlertTriggerFields'
import { describeMetricsCondition, toWritePayload, validateForm } from './metricsAlertUtils'

export function MetricsAlertCreateModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="" simple width={900}>
            {isOpen ? <MetricsAlertCreateModalContent onClose={onClose} /> : null}
        </LemonModal>
    )
}

function MetricsAlertCreateModalContent({ onClose }: { onClose: () => void }): JSX.Element {
    const formLogicProps = { alert: null, onSubmitSuccess: onClose }
    const { isAlertFormSubmitting, alertFormChanged, alertForm } = useValues(metricsAlertFormLogic(formLogicProps))
    const { touchAlertFormField } = useActions(metricsAlertFormLogic(formLogicProps))
    const {
        name: nameError,
        query: queryError,
        threshold: thresholdError,
        datapointsToAlarm: datapointsError,
        labels: labelsError,
    } = validateForm(alertForm)
    const configureCannotAdvanceReason = nameError ?? queryError
    const triggerCannotAdvanceReason = thresholdError ?? datapointsError
    const payload = toWritePayload(alertForm)

    const steps: AlertWizardStep[] = [
        {
            key: 'configure',
            title: 'Configure',
            description: 'Name the alert and write the PromQL query it checks.',
            canAdvance: !configureCannotAdvanceReason,
            cannotAdvanceReason: configureCannotAdvanceReason,
            renderContent: (showValidationErrors) => (
                <div className="max-w-2xl">
                    <MetricsAlertQueryFields
                        nameError={showValidationErrors ? nameError : undefined}
                        queryError={showValidationErrors ? queryError : undefined}
                    />
                </div>
            ),
        },
        {
            key: 'trigger',
            title: 'Set trigger',
            description: 'Set when a series fires the alert and reduce notification noise if needed.',
            canAdvance: !triggerCannotAdvanceReason,
            cannotAdvanceReason: triggerCannotAdvanceReason,
            renderContent: (showValidationErrors) => (
                <div className="max-w-2xl">
                    <MetricsAlertTriggerFields thresholdError={showValidationErrors ? thresholdError : undefined} />
                </div>
            ),
        },
        {
            key: 'notify',
            title: 'Notify',
            description: 'Label the alert so alert routes can send its notifications.',
            canAdvance: !labelsError,
            cannotAdvanceReason: labelsError,
            content: (
                <div className="max-w-2xl">
                    <MetricsAlertNotifyFields />
                </div>
            ),
        },
        {
            key: 'review',
            title: 'Review',
            description: 'Confirm the alert before you create it.',
            content: (
                <WizardReview
                    notice={
                        alertForm.labels.length === 0 ? (
                            <LemonBanner type="info">
                                This alert has no labels, so only routes with no conditions send its notifications.
                            </LemonBanner>
                        ) : undefined
                    }
                    items={[
                        { label: 'Name', value: payload.name },
                        { label: 'Query', value: <code className="break-all">{payload.source_config.query}</code> },
                        { label: 'Fires when', value: describeMetricsCondition(payload.source_config.condition) },
                        {
                            label: 'Group by',
                            value: alertForm.groupByLabels.length ? alertForm.groupByLabels.join(', ') : 'None',
                        },
                        {
                            label: 'Noise reduction',
                            value: `${alertForm.datapointsToAlarm} of ${alertForm.evaluationPeriods} checks must match`,
                        },
                        { label: 'Notification cooldown', value: `${alertForm.cooldownMinutes} minutes` },
                        {
                            label: 'Labels',
                            value: alertForm.labels.length
                                ? alertForm.labels.map(({ name, value }) => `${name}=${value}`).join(', ')
                                : 'None',
                        },
                    ]}
                />
            ),
        },
    ]

    return (
        <BindLogic logic={metricsAlertFormLogic} props={formLogicProps}>
            <Form
                logic={metricsAlertFormLogic}
                props={formLogicProps}
                formKey="alertForm"
                enableFormOnSubmit
                className="LemonModal__layout"
            >
                <AlertWizard
                    title="New metrics alert"
                    steps={steps}
                    isSubmitting={isAlertFormSubmitting}
                    hasChanges={alertFormChanged}
                    onBack={onClose}
                    onSubmitAttempted={() => touchAlertFormField('name')}
                />
            </Form>
        </BindLogic>
    )
}
