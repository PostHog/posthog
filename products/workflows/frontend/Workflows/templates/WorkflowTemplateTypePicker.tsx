import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import type { WorkflowTemplateTypeFilter } from '../workflowTypeFilters'
import { workflowTemplatesLogic } from './workflowTemplatesLogic'

export function WorkflowTemplateTypePicker(): JSX.Element {
    const { typeFilter } = useValues(workflowTemplatesLogic)
    const { setTypeFilter } = useActions(workflowTemplatesLogic)

    return (
        <LemonSegmentedButton<WorkflowTemplateTypeFilter>
            size="small"
            value={typeFilter}
            onChange={setTypeFilter}
            options={[
                { value: 'all', label: 'All', 'data-attr': 'workflow-template-type-all' },
                { value: 'messaging', label: 'Messaging', 'data-attr': 'workflow-template-type-messaging' },
                { value: 'automation', label: 'Automation', 'data-attr': 'workflow-template-type-automation' },
            ]}
        />
    )
}
