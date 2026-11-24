import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { Dialog, DialogContent } from '@posthog/quill'

import { closesIntoLemonPopover } from 'lib/components/QuillSurface/closesIntoLemonPopover'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { AlertWizardStep } from 'products/alerts/frontend/components/AlertWizard'
import { QuillAlertEditorFormDetails } from 'products/alerts/frontend/components/QuillAlertEditorFormDetails'
import { QuillAlertWizard } from 'products/alerts/frontend/components/QuillAlertWizard'
import { platformAlertDestinationsLogic } from 'products/alerts_platform/frontend/destinations/platformAlertDestinationsLogic'

import { logsAlertDestinationsLogicProps } from './logsAlertDestinations'
import { getLogsAlertCreateValidation } from './logsAlertEditorModel'
import { logsAlertFormLogic } from './logsAlertFormLogic'
import { LogsAlertNotifications } from './LogsAlertNotifications'
import { QuillLogsAlertFilters } from './QuillLogsAlertFilters'
import { QuillLogsAlertReview } from './QuillLogsAlertReview'
import { QuillLogsAlertSimulation } from './QuillLogsAlertSimulation'
import { QuillLogsAlertTrigger } from './QuillLogsAlertTrigger'

interface QuillLogsAlertCreateModalProps {
    isOpen: boolean
    onClose: () => void
}

export function QuillLogsAlertCreateModal({ isOpen, onClose }: QuillLogsAlertCreateModalProps): JSX.Element {
    return (
        <Dialog
            open={isOpen}
            // The service and filter pickers open Lemon popovers that portal outside the dialog. A modal dialog would
            // make them inert and pull focus back, so the dialog stays non-modal and ignores clicks that land in them.
            modal={false}
            onOpenChange={(open, details) => {
                if (closesIntoLemonPopover(open, details)) {
                    details.cancel()
                    return
                }
                if (!open) {
                    onClose()
                }
            }}
        >
            <DialogContent className="sm:max-w-225">
                {isOpen ? <QuillLogsAlertCreateModalContent onClose={onClose} /> : null}
            </DialogContent>
        </Dialog>
    )
}

function QuillLogsAlertCreateModalContent({ onClose }: { onClose: () => void }): JSX.Element {
    const formLogicProps = { alert: null, onSubmitSuccess: onClose }
    const { isAlertFormSubmitting, alertFormChanged, alertForm, alertFormValidationErrors, canGroup } = useValues(
        logsAlertFormLogic(formLogicProps)
    )
    const { touchAlertFormField } = useActions(logsAlertFormLogic(formLogicProps))
    const { pendingDestinations } = useValues(platformAlertDestinationsLogic(logsAlertDestinationsLogicProps()))
    const { nameError, filterError, configurationCannotAdvanceReason, triggerCannotAdvanceReason } =
        getLogsAlertCreateValidation(alertForm, alertFormValidationErrors)

    const steps: AlertWizardStep[] = [
        {
            key: 'configure',
            title: 'Configure',
            description: 'Select matching logs and set when this alert fires.',
            canAdvance: !configurationCannotAdvanceReason,
            cannotAdvanceReason: configurationCannotAdvanceReason,
            renderContent: (showValidationErrors) => (
                <div className="flex max-w-2xl flex-col gap-5">
                    <QuillAlertEditorFormDetails nameError={showValidationErrors ? nameError : undefined} />
                    <QuillLogsAlertFilters filterError={showValidationErrors ? filterError : undefined} />
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
                <div className="flex flex-col gap-6">
                    <QuillLogsAlertTrigger />
                    <QuillLogsAlertSimulation embedded />
                </div>
            ),
        },
        {
            key: 'notify',
            title: 'Notify',
            description: 'Choose where to send alert events.',
            content: (
                <div className="max-w-2xl">
                    <QuillSurfaceContext.Provider value>
                        <LogsAlertNotifications />
                    </QuillSurfaceContext.Provider>
                </div>
            ),
        },
        {
            key: 'review',
            title: 'Review',
            description: 'Confirm the alert before you create it.',
            content: (
                <QuillLogsAlertReview
                    alertForm={alertForm}
                    pendingDestinations={pendingDestinations}
                    canGroup={canGroup}
                />
            ),
        },
    ]

    return (
        <BindLogic logic={logsAlertFormLogic} props={formLogicProps}>
            <Form
                logic={logsAlertFormLogic}
                props={formLogicProps}
                formKey="alertForm"
                enableFormOnSubmit
                className="contents"
            >
                <QuillAlertWizard
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
