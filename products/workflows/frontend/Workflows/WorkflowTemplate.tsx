import { BindLogic, useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { HogFlowEditor } from './hogflows/HogFlowEditor'
import { workflowTemplateEditingLogic } from './workflowTemplateEditingLogic'

export type WorkflowTemplateProps = {
    editTemplateId: string
}

export function WorkflowTemplate({ editTemplateId }: WorkflowTemplateProps): JSX.Element {
    const templateEditorLogicInstance = workflowTemplateEditingLogic({ editTemplateId })
    const { originalTemplate, templateLoading } = useValues(templateEditorLogicInstance)

    return (
        <div className="relative border rounded-md h-[calc(100vh-280px)]">
            <BindLogic logic={workflowTemplateEditingLogic} props={{ editTemplateId }}>
                {!originalTemplate && templateLoading ? (
                    <SpinnerOverlay />
                ) : (
                    <HogFlowEditor editTemplateId={editTemplateId} />
                )}
            </BindLogic>
        </div>
    )
}
