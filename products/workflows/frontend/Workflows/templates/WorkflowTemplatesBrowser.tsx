import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { WorkflowTemplateChooser } from './WorkflowTemplateChooser'
import { workflowTemplatesLogic } from './workflowTemplatesLogic'
import { WorkflowTemplateTypePicker } from './WorkflowTemplateTypePicker'

/** Workflow templates as a page of their own, for browsing outside the "New workflow" modal. */
export function WorkflowTemplatesBrowser(): JSX.Element {
    const { templateFilter } = useValues(workflowTemplatesLogic)
    const { setTemplateFilter } = useActions(workflowTemplatesLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2 items-center justify-between">
                <LemonInput
                    type="search"
                    placeholder="Search templates"
                    onChange={setTemplateFilter}
                    value={templateFilter}
                    className="max-w-80"
                />
                <WorkflowTemplateTypePicker />
            </div>
            <WorkflowTemplateChooser />
        </div>
    )
}
