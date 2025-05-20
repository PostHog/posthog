import '@xyflow/react/dist/style.css'

import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { Form } from 'kea-forms'
import { campaignLogic } from './campaignLogic'
import { WorkflowEditor } from './Workflows/WorkflowEditor'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { PageHeader } from 'lib/components/PageHeader'
import { messageTemplateLogic } from '../Library/messageTemplateLogic'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

// Wrapper component with ReactFlowProvider
export function Campaign(): JSX.Element {
    const { id, updateWorkflowJson } = useActions(campaignLogic)
    const { isTemplateSubmitting, templateChanged, messageLoading } = useValues(messageTemplateLogic)

    return (
        <div className="flex flex-col space-y-4">
            <Form logic={messageTemplateLogic} formKey="template">
                <PageHeader
                    buttons={
                        <>
                            {templateChanged && (
                                <LemonButton data-attr="cancel-message-template" type="secondary">
                                    Discard changes
                                </LemonButton>
                            )}
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                form="template"
                                loading={isTemplateSubmitting}
                                disabledReason={templateChanged ? undefined : 'No changes to save'}
                            >
                                {id === 'new' ? 'Create' : 'Save'}
                            </LemonButton>
                        </>
                    }
                />
                <div className="flex flex-wrap gap-4 items-start">
                    <div className="flex-1 self-start p-3 space-y-2 rounded border min-w-100 bg-surface-primary">
                        <LemonField name="name" label="Name">
                            <LemonInput disabled={messageLoading} />
                        </LemonField>

                        <LemonField
                            name="description"
                            label="Description"
                            info="Add a description to share context with other team members"
                        >
                            <LemonInput disabled={messageLoading} />
                        </LemonField>
                    </div>
                </div>
            </Form>
            <div className="relative h-[calc(100vh-300px)] border rounded-md">
                <WorkflowEditor setFlowData={updateWorkflowJson} />
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: Campaign,
    logic: campaignLogic,
}
