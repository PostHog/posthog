import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { useWindowSize } from 'lib/hooks/useWindowSize'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { newWorkflowLogic } from './newWorkflowLogic'
import { WorkflowTemplateChooser } from './templates/WorkflowTemplateChooser'
import { workflowTemplatesLogic } from './templates/workflowTemplatesLogic'

export function NewWorkflowModal(): JSX.Element {
    const { hideNewWorkflowModal } = useActions(newWorkflowLogic)
    const { newWorkflowModalVisible } = useValues(newWorkflowLogic)

    const { templateFilter, tagFilter, availableTags } = useValues(workflowTemplatesLogic)
    const { setTemplateFilter, setTagFilter } = useActions(workflowTemplatesLogic)
    const { isWindowLessThan } = useWindowSize()

    // A 1200px template grid has nothing to offer a phone, and the filter input opens the keyboard
    // the moment the modal does — going full screen buys back every pixel for the scroll pane.
    const isNarrow = isWindowLessThan('md')

    const tagOptions = [
        { value: null as string | null, label: 'All categories' },
        ...availableTags.map((tag) => ({ value: tag as string | null, label: tag })),
    ]

    return (
        <LemonModal
            onClose={hideNewWorkflowModal}
            isOpen={newWorkflowModalVisible}
            width={1200}
            fullScreen={isNarrow}
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
                            autoFocus
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
