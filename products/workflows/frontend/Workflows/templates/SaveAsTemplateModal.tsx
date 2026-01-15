import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { userLogic } from 'scenes/userLogic'

import { WorkflowTemplateLogicProps, workflowTemplateLogic } from './workflowTemplateLogic'

export function TemplateJsonModal(props: WorkflowTemplateLogicProps = {}): JSX.Element {
    const logic = workflowTemplateLogic(props)
    const { templateJsonModalVisible, templateJson } = useValues(logic)
    const { hideTemplateJsonModal } = useActions(logic)

    return (
        <LemonModal
            onClose={hideTemplateJsonModal}
            isOpen={templateJsonModalVisible}
            title="Template JSON"
            width="60vw"
            footer={
                <LemonButton type="secondary" onClick={hideTemplateJsonModal}>
                    Close
                </LemonButton>
            }
        >
            <div className="space-y-4">
                <div className="p-3 bg-primary-highlight rounded border">
                    Copy your template and create or edit the template file in the posthog repository under{' '}
                    <code className="text-xs">products/workflows/backend/templates</code>
                </div>
                <div className="relative">
                    <div className="absolute top-2 right-2 z-10">
                        <LemonButton
                            icon={<IconCopy />}
                            size="small"
                            onClick={() => copyToClipboard(templateJson, 'template JSON')}
                        >
                            Copy
                        </LemonButton>
                    </div>
                    <CodeEditorResizeable
                        language="json"
                        value={templateJson}
                        height={500}
                        options={{
                            readOnly: true,
                            minimap: { enabled: false },
                        }}
                    />
                </div>
            </div>
        </LemonModal>
    )
}

export function SaveAsTemplateModal(props: WorkflowTemplateLogicProps = {}): JSX.Element {
    const { user } = useValues(userLogic)
    const logic = workflowTemplateLogic(props)
    const { saveAsTemplateModalVisible, isTemplateFormSubmitting, templateForm, isEditMode } = useValues(logic)
    const { hideSaveAsTemplateModal, submitTemplateForm, showTemplateJsonModal } = useActions(logic)

    const isGlobalTemplate = templateForm.scope === 'global'
    const showSeeJsonButton = user?.is_staff && isGlobalTemplate

    return (
        <>
            <TemplateJsonModal {...props} />
            <LemonModal
                onClose={hideSaveAsTemplateModal}
                isOpen={saveAsTemplateModalVisible}
                title={isEditMode ? 'Update template' : 'Save as template'}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={hideSaveAsTemplateModal}>
                            Cancel
                        </LemonButton>
                        {showSeeJsonButton ? (
                            <LemonButton type="primary" onClick={showTemplateJsonModal}>
                                See JSON
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="primary"
                                onClick={submitTemplateForm}
                                loading={isTemplateFormSubmitting}
                                disabledReason={!templateForm.name ? 'Name is required' : undefined}
                            >
                                {isEditMode ? 'Update template' : 'Save template'}
                            </LemonButton>
                        )}
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
        </>
    )
}
