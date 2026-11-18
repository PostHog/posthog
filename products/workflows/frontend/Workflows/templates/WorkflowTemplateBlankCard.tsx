import { useActions } from 'kea'

import { newWorkflowLogic } from '../newWorkflowLogic'
import { WorkflowTemplateBlankPreview } from './WorkflowTemplateBlankPreview'
import { WorkflowTemplateCard } from './WorkflowTemplateCard'

/** The "blank workflow" choice: opens a new workflow with no template. */
export function WorkflowTemplateBlankCard({ 'data-attr': dataAttr }: { 'data-attr': string }): JSX.Element {
    const { createEmptyWorkflow } = useActions(newWorkflowLogic)
    return (
        <WorkflowTemplateCard
            name="Blank workflow"
            description="Start from scratch and add your own trigger and steps."
            preview={<WorkflowTemplateBlankPreview />}
            onClick={createEmptyWorkflow}
            data-attr={dataAttr}
        />
    )
}
