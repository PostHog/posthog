import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { isMobile } from 'lib/utils/dom'

import { newWorkflowLogic } from './newWorkflowLogic'
import { WorkflowTemplateChooser } from './templates/WorkflowTemplateChooser'
import { workflowTemplatesLogic } from './templates/workflowTemplatesLogic'

export function NewWorkflowModal(): JSX.Element {
    const { hideNewWorkflowModal } = useActions(newWorkflowLogic)
    const { newWorkflowModalVisible } = useValues(newWorkflowLogic)

    const { templateFilter, tagFilter, availableTags } = useValues(workflowTemplatesLogic)
    const { setTemplateFilter, setTagFilter } = useActions(workflowTemplatesLogic)

    const tagOptions = [
        { value: null as string | null, label: 'All categories' },
        ...availableTags.map((tag) => ({ value: tag as string | null, label: tag })),
    ]

    return (
        <LemonModal
            onClose={hideNewWorkflowModal}
            isOpen={newWorkflowModalVisible}
            width={1200}
            title="Create a workflow"
            data-attr="new-workflow-chooser"
            description={
                <div className="flex flex-col gap-2">
                    <div>Choose a template or start with a blank slate</div>
                    <div className="flex gap-2 items-center">
                        <LemonInput
                            type="search"
                            placeholder="Filter templates"
                            onChange={setTemplateFilter}
                            value={templateFilter}
                            fullWidth={true}
                            // On a phone, a focused input makes iOS pan the whole viewport on swipe,
                            // so the template list can't be scrolled until the keyboard is dismissed.
                            autoFocus={!isMobile()}
                        />
                        {availableTags.length > 0 && (
                            <LemonSelect
                                className="shrink-0 min-w-56 whitespace-nowrap"
                                options={tagOptions}
                                value={tagFilter}
                                onChange={(value) => setTagFilter(value)}
                                dropdownMatchSelectWidth={false}
                            />
                        )}
                    </div>
                </div>
            }
        >
            <div className="NewWorkflowModal">
                <WorkflowTemplateChooser showEmptyWorkflow />
            </div>
        </LemonModal>
    )
}
