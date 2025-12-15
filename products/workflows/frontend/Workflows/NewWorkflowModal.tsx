import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { WorkflowTemplateChooser } from './WorkflowTemplateChooser'
import { newWorkflowLogic } from './newWorkflowLogic'
import { workflowsLogic } from './workflowsLogic'

export function NewWorkflowModal(): JSX.Element {
    const { hideNewWorkflowModal } = useActions(newWorkflowLogic)
    const { newWorkflowModalVisible } = useValues(newWorkflowLogic)

    const { workflowTemplates, workflowTemplatesLoading, templateFilter } = useValues(workflowsLogic)
    const { loadWorkflowTemplates, setTemplateFilter } = useActions(workflowsLogic)

    useEffect(() => {
        if (newWorkflowModalVisible && workflowTemplates.length === 0 && !workflowTemplatesLoading) {
            loadWorkflowTemplates()
        }
        // We don't want this to trigger on changes to workflowTemplates or workflowTemplatesLoading
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [newWorkflowModalVisible])

    return (
        <LemonModal
            onClose={hideNewWorkflowModal}
            isOpen={newWorkflowModalVisible}
            title="Create a workflow"
            data-attr="new-workflow-chooser"
            description={
                <div className="flex flex-col gap-2">
                    <div>Choose a template or start with a blank slate</div>
                    <div>
                        <LemonInput
                            type="search"
                            placeholder="Filter templates"
                            onChange={setTemplateFilter}
                            value={templateFilter}
                            fullWidth={true}
                            autoFocus
                        />
                    </div>
                </div>
            }
        >
            <div className="NewWorkflowModal">
                <WorkflowTemplateChooser />
            </div>
        </LemonModal>
    )
}
