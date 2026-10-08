import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { WorkflowTemplateChooser } from './WorkflowTemplateChooser'
import { workflowTemplatesLogic } from './workflowTemplatesLogic'
import { WorkflowTemplateTypePicker } from './WorkflowTemplateTypePicker'

/** Workflow templates as a page of their own, for browsing outside the "New workflow" modal. */
export function WorkflowTemplatesBrowser(): JSX.Element {
    const { templateFilter, tagFilter, availableTags } = useValues(workflowTemplatesLogic)
    const { setTemplateFilter, setTagFilter } = useActions(workflowTemplatesLogic)

    const tagOptions = [
        { value: null as string | null, label: 'All categories' },
        ...availableTags.map((tag) => ({ value: tag as string | null, label: tag })),
    ]

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
                <div className="flex flex-wrap gap-2 items-center">
                    <WorkflowTemplateTypePicker />
                    {availableTags.length > 0 && (
                        <LemonSelect
                            className="shrink-0 min-w-56 whitespace-nowrap"
                            options={tagOptions}
                            value={tagFilter}
                            onChange={(value) => setTagFilter(value)}
                            dropdownMatchSelectWidth={false}
                            data-attr="workflow-templates-category"
                        />
                    )}
                </div>
            </div>
            <WorkflowTemplateChooser />
        </div>
    )
}
