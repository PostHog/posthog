import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonModal } from '@posthog/lemon-ui'

import { WizardReview } from 'lib/components/WizardReview'

import { AlertEditorFormDetails } from 'products/alerts/frontend/components/AlertEditor'
import { AlertWizard, AlertWizardStep } from 'products/alerts/frontend/components/AlertWizard'
import { platformAlertDestinationsLogic } from 'products/alerts_platform/frontend/destinations/platformAlertDestinationsLogic'
import { PlatformAlertCreateDestinationApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { logsAlertDestinationsLogicProps } from './logsAlertDestinations'
import { buildLogsAlertReviewItems, getLogsAlertCreateValidation } from './logsAlertEditorModel'
import { LogsAlertFilters, LogsAlertTrigger } from './LogsAlertForm'
import { logsAlertFormLogic, LogsAlertFormType } from './logsAlertFormLogic'
import { LogsAlertNotifications } from './LogsAlertNotifications'
import { LogsAlertSimulation } from './LogsAlertSimulation'

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
    const { isAlertFormSubmitting, alertFormChanged, alertForm, alertFormValidationErrors, canGroup } = useValues(
        logsAlertFormLogic(formLogicProps)
    )
    const { touchAlertFormField } = useActions(logsAlertFormLogic(formLogicProps))
    const { pendingDestinations } = useValues(platformAlertDestinationsLogic(logsAlertDestinationsLogicProps()))
    const { nameError, filterError, configurationCannotAdvanceReason, triggerCannotAdvanceReason } =
        getLogsAlertCreateValidation(alertForm, alertFormValidationErrors)
    const steps = buildLogsAlertWizardSteps({
        alertForm,
        pendingDestinations,
        configurationCannotAdvanceReason,
        triggerCannotAdvanceReason,
        nameError,
        filterError,
        canGroup,
    })

    return (
        <BindLogic logic={logsAlertFormLogic} props={formLogicProps}>
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
    )
}

function buildLogsAlertWizardSteps({
    alertForm,
    pendingDestinations,
    configurationCannotAdvanceReason,
    triggerCannotAdvanceReason,
    nameError,
    filterError,
    canGroup,
}: {
    alertForm: LogsAlertFormType
    pendingDestinations: PlatformAlertCreateDestinationApi[]
    configurationCannotAdvanceReason: string | undefined
    triggerCannotAdvanceReason: string | undefined
    nameError: string | undefined
    filterError: string | undefined
    canGroup: boolean
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
            canAdvance: !triggerCannotAdvanceReason,
            cannotAdvanceReason: triggerCannotAdvanceReason,
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
            content: (
                <LogsAlertReview alertForm={alertForm} pendingDestinations={pendingDestinations} canGroup={canGroup} />
            ),
        },
    ]
}

function LogsAlertReview({
    alertForm,
    pendingDestinations,
    canGroup,
}: {
    alertForm: LogsAlertFormType
    pendingDestinations: PlatformAlertCreateDestinationApi[]
    canGroup: boolean
}): JSX.Element {
    return (
        <WizardReview
            notice={
                pendingDestinations.length === 0 ? (
                    <LemonBanner type="warning">
                        This alert will run without notifications. Go back to Notify to add a destination.
                    </LemonBanner>
                ) : undefined
            }
            items={buildLogsAlertReviewItems(alertForm, pendingDestinations, canGroup)}
        />
    )
}
