import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonModal } from '@posthog/lemon-ui'

import { WizardReview } from 'lib/components/WizardReview'

import { AlertEditorFormDetails } from 'products/alerts/frontend/components/AlertEditor'
import { AlertWizard, AlertWizardStep } from 'products/alerts/frontend/components/AlertWizard'

import { ScannerAlertFormType, scannerAlertFormLogic } from '../scannerAlertFormLogic'
import { scannerAlertNotificationLogic } from '../scannerAlertNotificationLogic'
import { PendingVisionAlertNotification } from '../scannerAlertUtils'
import { ScannerAlertKindPicker, ScannerAlertSelectionFields, ScannerAlertTrigger } from './ScannerAlertForm'
import { ScannerAlertNotifications } from './ScannerAlertNotifications'

interface ScannerAlertCreateModalProps {
    scannerId: string
    scannerType?: string
    isOpen: boolean
    onClose: () => void
}

export function ScannerAlertCreateModal({
    scannerId,
    scannerType,
    isOpen,
    onClose,
}: ScannerAlertCreateModalProps): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="" simple width={900}>
            {isOpen ? (
                <ScannerAlertCreateModalContent scannerId={scannerId} scannerType={scannerType} onClose={onClose} />
            ) : null}
        </LemonModal>
    )
}

function ScannerAlertCreateModalContent({
    scannerId,
    scannerType,
    onClose,
}: {
    scannerId: string
    scannerType?: string
    onClose: () => void
}): JSX.Element {
    const formLogicProps = { scannerId, alert: null, onSubmitSuccess: onClose }
    const { isAlertFormSubmitting, alertFormChanged, alertForm } = useValues(scannerAlertFormLogic(formLogicProps))
    const { touchAlertFormField } = useActions(scannerAlertFormLogic(formLogicProps))
    const { pendingNotifications } = useValues(scannerAlertNotificationLogic({}))

    const nameError = alertForm.name.trim() ? undefined : 'Enter an alert name.'
    const thresholdError =
        alertForm.kind === 'metric' && alertForm.threshold === null ? 'Enter a threshold.' : undefined

    const steps: AlertWizardStep[] = [
        {
            key: 'configure',
            title: 'Configure',
            description: 'Name the alert and pick its type.',
            canAdvance: !nameError,
            cannotAdvanceReason: nameError,
            renderContent: (showValidationErrors) => (
                <div className="max-w-2xl space-y-5">
                    <AlertEditorFormDetails nameError={showValidationErrors ? nameError : undefined} />
                    <ScannerAlertKindPicker />
                </div>
            ),
        },
        {
            key: 'trigger',
            title: 'Set trigger',
            description: 'Choose which observations count and when the alert fires.',
            canAdvance: !thresholdError,
            cannotAdvanceReason: thresholdError,
            renderContent: (showValidationErrors) => (
                <div className="max-w-2xl space-y-6">
                    <ScannerAlertSelectionFields scannerType={scannerType} />
                    <ScannerAlertTrigger thresholdError={showValidationErrors ? thresholdError : undefined} />
                </div>
            ),
        },
        {
            key: 'notify',
            title: 'Notify',
            description: 'Choose where to send alert notifications.',
            content: (
                <div className="max-w-2xl">
                    <ScannerAlertNotifications />
                </div>
            ),
        },
        {
            key: 'review',
            title: 'Review',
            description: 'Confirm the alert before you create it.',
            content: <ScannerAlertReview alertForm={alertForm} pendingNotifications={pendingNotifications} />,
        },
    ]

    return (
        <BindLogic logic={scannerAlertFormLogic} props={formLogicProps}>
            <BindLogic logic={scannerAlertNotificationLogic} props={{}}>
                <Form
                    logic={scannerAlertFormLogic}
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

function ScannerAlertReview({
    alertForm,
    pendingNotifications,
}: {
    alertForm: ScannerAlertFormType
    pendingNotifications: PendingVisionAlertNotification[]
}): JSX.Element {
    const firesWhen =
        alertForm.kind === 'match'
            ? 'every matching observation, bundled into one notification per minute'
            : `${alertForm.metric === 'avg_score' ? 'average score' : 'matching observation count'} is ${
                  alertForm.direction === 'below' ? 'at or below' : 'at or above'
              } ${alertForm.threshold} in the last ${alertForm.windowDays === 1 ? '24 hours' : `${alertForm.windowDays} days`}`
    const watches =
        [
            alertForm.verdict.length ? `verdict ${alertForm.verdict.join(', ')}` : null,
            alertForm.tags.length ? `tags ${alertForm.tags.join(', ')}` : null,
            alertForm.minScore !== null ? `score ≥ ${alertForm.minScore}` : null,
            alertForm.maxScore !== null ? `score ≤ ${alertForm.maxScore}` : null,
        ]
            .filter(Boolean)
            .join(', ') || 'all observations'
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
                {
                    label: 'Type',
                    value: alertForm.kind === 'match' ? 'Every matching observation' : 'Metric threshold',
                },
                { label: 'Watches', value: watches },
                { label: 'Fires when', value: firesWhen },
                { label: 'Notifies', value: notificationSummary },
            ]}
        />
    )
}
