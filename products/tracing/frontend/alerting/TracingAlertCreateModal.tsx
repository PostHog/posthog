import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonModal } from '@posthog/lemon-ui'

import { AlertEditor, AlertEditorFormDetails } from 'products/alerts/frontend/components/AlertEditor'

import { TracingAlertForm } from './TracingAlertForm'
import { tracingAlertFormLogic } from './tracingAlertFormLogic'

export function TracingAlertCreateModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} width={800} title="">
            {isOpen ? <TracingAlertCreateModalContent onClose={onClose} /> : null}
        </LemonModal>
    )
}

function TracingAlertCreateModalContent({ onClose }: { onClose: () => void }): JSX.Element {
    const logicProps = { alert: null, onSubmitSuccess: onClose }
    const { alertFormChanged, isAlertFormSubmitting, alertFormErrors } = useValues(tracingAlertFormLogic(logicProps))

    return (
        <Form logic={tracingAlertFormLogic} props={logicProps} formKey="alertForm" enableFormOnSubmit>
            <AlertEditor
                title="New alert"
                description="Get notified when traces cross a threshold you define."
                isEditing={false}
                isSubmitting={isAlertFormSubmitting}
                hasChanges={alertFormChanged}
            >
                <div className="space-y-5">
                    <AlertEditorFormDetails
                        nameDataAttr="tracing-alert-name"
                        nameError={typeof alertFormErrors.name === 'string' ? alertFormErrors.name : undefined}
                    />
                    <TracingAlertForm />
                </div>
            </AlertEditor>
        </Form>
    )
}
