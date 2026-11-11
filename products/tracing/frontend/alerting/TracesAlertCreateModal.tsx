import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonModal } from '@posthog/lemon-ui'

import { WizardReview } from 'lib/components/WizardReview'

import { UniversalFiltersGroup } from '~/types'

import { AlertEditorFormDetails } from 'products/alerts/frontend/components/AlertEditor'
import { AlertWizard, AlertWizardStep } from 'products/alerts/frontend/components/AlertWizard'
import { platformAlertDestinationsLogic } from 'products/alerts_platform/frontend/destinations/platformAlertDestinationsLogic'
import { PlatformAlertNotifications } from 'products/alerts_platform/frontend/destinations/PlatformAlertNotifications'

import { TracesAlertFilterFields } from './TracesAlertFilterFields'
import { tracesAlertFormLogic } from './tracesAlertFormLogic'
import { TracesAlertTriggerFields } from './TracesAlertTriggerFields'
import {
    GROUP_BY_OPTIONS,
    NEW_ALERT_DESTINATIONS,
    describeTracesCondition,
    describeTracesScope,
    errorText,
    toWritePayload,
} from './tracesAlertUtils'

interface TracesAlertCreateModalProps {
    isOpen: boolean
    onClose: () => void
    viewerFilters: { serviceNames: string[]; filterGroup: UniversalFiltersGroup }
}

export function TracesAlertCreateModal({ isOpen, onClose, viewerFilters }: TracesAlertCreateModalProps): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="" simple width={900}>
            {isOpen ? <TracesAlertCreateModalContent onClose={onClose} viewerFilters={viewerFilters} /> : null}
        </LemonModal>
    )
}

function TracesAlertCreateModalContent({
    onClose,
    viewerFilters,
}: Omit<TracesAlertCreateModalProps, 'isOpen'>): JSX.Element {
    const formLogicProps = { alert: null, viewerFilters, onSubmitSuccess: onClose }
    const { isAlertFormSubmitting, alertFormChanged, alertForm, alertFormValidationErrors } = useValues(
        tracesAlertFormLogic(formLogicProps)
    )
    const { touchAlertFormField } = useActions(tracesAlertFormLogic(formLogicProps))
    // Mounted here, not only in the notify step, so destinations added there survive moving between steps.
    const { pendingDestinations } = useValues(platformAlertDestinationsLogic(NEW_ALERT_DESTINATIONS))
    const nameError = errorText(alertFormValidationErrors.name)
    const thresholdError = errorText(alertFormValidationErrors.threshold)
    const triggerCannotAdvanceReason =
        thresholdError ??
        errorText(alertFormValidationErrors.groupBy) ??
        errorText(alertFormValidationErrors.evaluationPeriods) ??
        errorText(alertFormValidationErrors.datapointsToAlarm) ??
        errorText(alertFormValidationErrors.cooldownMinutes)
    const payload = toWritePayload(alertForm)

    const steps: AlertWizardStep[] = [
        {
            key: 'configure',
            title: 'Configure',
            description: 'Name the alert and pick the requests it measures.',
            canAdvance: !nameError,
            cannotAdvanceReason: nameError,
            renderContent: (showValidationErrors) => (
                <div className="max-w-2xl">
                    <div className="space-y-5">
                        <AlertEditorFormDetails nameError={showValidationErrors ? nameError : undefined} />
                        <TracesAlertFilterFields />
                    </div>
                </div>
            ),
        },
        {
            key: 'trigger',
            title: 'Set trigger',
            description: 'Set when the alert fires and reduce notification noise if needed.',
            canAdvance: !triggerCannotAdvanceReason,
            cannotAdvanceReason: triggerCannotAdvanceReason,
            renderContent: (showValidationErrors) => (
                <div className="max-w-2xl">
                    <TracesAlertTriggerFields thresholdError={showValidationErrors ? thresholdError : undefined} />
                </div>
            ),
        },
        {
            key: 'notify',
            title: 'Notify',
            description: 'Choose where to send alert events.',
            content: (
                <div className="max-w-2xl">
                    <PlatformAlertNotifications {...NEW_ALERT_DESTINATIONS} />
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
                        pendingDestinations.length === 0 ? (
                            <LemonBanner type="warning">
                                This alert will run without notifications. Go back to Notify to add a destination.
                            </LemonBanner>
                        ) : undefined
                    }
                    items={[
                        { label: 'Name', value: payload.name },
                        { label: 'Requests', value: describeTracesScope(payload.source_config) },
                        { label: 'Fires when', value: describeTracesCondition(payload.source_config.condition) },
                        {
                            label: 'Check separately for',
                            value: GROUP_BY_OPTIONS.find((option) => option.value === alertForm.groupBy)?.label,
                        },
                        {
                            label: 'Noise reduction',
                            value: `${alertForm.datapointsToAlarm} of ${alertForm.evaluationPeriods} checks must match`,
                        },
                        { label: 'Notification cooldown', value: `${alertForm.cooldownMinutes} minutes` },
                        {
                            label: 'Notifies',
                            value: pendingDestinations.length
                                ? `${pendingDestinations.length} notification destination${pendingDestinations.length === 1 ? '' : 's'}`
                                : 'No notification destinations',
                        },
                    ]}
                />
            ),
        },
    ]

    return (
        <BindLogic logic={tracesAlertFormLogic} props={formLogicProps}>
            <Form
                logic={tracesAlertFormLogic}
                props={formLogicProps}
                formKey="alertForm"
                enableFormOnSubmit
                className="LemonModal__layout"
            >
                <AlertWizard
                    title="New traces alert"
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
