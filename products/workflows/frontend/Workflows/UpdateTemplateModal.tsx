import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { userLogic } from 'scenes/userLogic'

import { WorkflowTemplateEditorLogicProps, workflowTemplateEditingLogic } from './workflowTemplateEditingLogic'

interface UpdateTemplateModalProps {
    templateProps: WorkflowTemplateEditorLogicProps
}

export function UpdateTemplateModal({ templateProps }: UpdateTemplateModalProps): JSX.Element {
    const { user } = useValues(userLogic)
    const templateLogic = workflowTemplateEditingLogic(templateProps)
    const { updateTemplateModalVisible, isUpdateTemplateFormSubmitting, updateTemplateForm } = useValues(templateLogic)
    const { hideUpdateTemplateModal, submitUpdateTemplateForm } = useActions(templateLogic)

    return (
        <LemonModal
            onClose={hideUpdateTemplateModal}
            isOpen={updateTemplateModalVisible}
            title="Update template"
            footer={
                <>
                    <LemonButton type="secondary" onClick={hideUpdateTemplateModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitUpdateTemplateForm}
                        loading={isUpdateTemplateFormSubmitting}
                        disabledReason={!updateTemplateForm.name ? 'Name is required' : undefined}
                    >
                        Update template
                    </LemonButton>
                </>
            }
        >
            <Form logic={workflowTemplateEditingLogic} props={templateProps} formKey="updateTemplateForm">
                <div className="space-y-4">
                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="Template name" autoFocus />
                    </LemonField>

                    <LemonField name="description" label="Description (optional)">
                        <LemonTextArea placeholder="Template description" rows={3} />
                    </LemonField>

                    <LemonField name="image_url" label="Image URL (optional)">
                        <LemonInput placeholder="https://example.com/image.png" />
                    </LemonField>

                    {user?.is_staff && (
                        <LemonField name="scope" label="Scope">
                            <LemonSelect
                                value={updateTemplateForm.scope}
                                options={[
                                    { value: 'team', label: 'Team only' },
                                    { value: 'global', label: 'Official (visible to everyone)' },
                                ]}
                            />
                        </LemonField>
                    )}
                </div>
            </Form>
        </LemonModal>
    )
}
