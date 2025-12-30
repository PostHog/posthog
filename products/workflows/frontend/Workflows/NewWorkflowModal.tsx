import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { WorkflowTemplateChooser } from './WorkflowTemplateChooser'
import { newWorkflowLogic } from './newWorkflowLogic'
import { workflowTemplatesLogic } from './workflowTemplatesLogic'

export function NewWorkflowModal(): JSX.Element {
    const { hideNewWorkflowModal } = useActions(newWorkflowLogic)
    const { newWorkflowModalVisible } = useValues(newWorkflowLogic)

    const { templateFilter } = useValues(workflowTemplatesLogic)
    const { setTemplateFilter } = useActions(workflowTemplatesLogic)

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
                    <div className="text-xs text-muted">
                        We're still expanding our portfolio of templates. Check back soon if you can't find what you're
                        looking for!
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
