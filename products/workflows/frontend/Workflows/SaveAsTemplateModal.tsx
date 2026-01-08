import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { userLogic } from 'scenes/userLogic'

import { WorkflowTemplateLogicProps, workflowTemplateLogic } from './workflowTemplateLogic'

export function SaveAsTemplateModal(props: WorkflowTemplateLogicProps = {}): JSX.Element {
    const { user } = useValues(userLogic)
    const logic = workflowTemplateLogic(props)
    const { saveAsTemplateModalVisible, isTemplateFormSubmitting, templateForm, isEditMode } = useValues(logic)
    const { hideSaveAsTemplateModal, submitTemplateForm } = useActions(logic)

    return (
        <LemonModal
            onClose={hideSaveAsTemplateModal}
            isOpen={saveAsTemplateModalVisible}
            title={isEditMode ? 'Update template' : 'Save as template'}
            footer={
                <>
                    <LemonButton type="secondary" onClick={hideSaveAsTemplateModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitTemplateForm}
                        loading={isTemplateFormSubmitting}
                        disabledReason={!templateForm.name ? 'Name is required' : undefined}
                    >
                        {isEditMode ? 'Update template' : 'Save template'}
                    </LemonButton>
                </>
            }
        >
            <Form logic={workflowTemplateLogic} props={props} formKey="templateForm">
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
                                value={templateForm.scope}
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
