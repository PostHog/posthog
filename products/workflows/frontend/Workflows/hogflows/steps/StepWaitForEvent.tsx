import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { useDebouncedNameInput } from './utils'

export function StepWaitForEventConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'wait_for_event' }>>
}): JSX.Element {
    const action = node.data
    const { event_filters, max_wait_duration } = action.config

    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    const { localName: localEventName, handleNameChange } = useDebouncedNameInput(event_filters, (updatedEventFilters) =>
        partialSetWorkflowActionConfig(action.id, { event_filters: updatedEventFilters })
    )

    return (
        <>
            <StepSchemaErrors />

            <div className="flex flex-col gap-1">
                <LemonLabel>Maximum wait time</LemonLabel>
                <HogFlowDuration
                    value={max_wait_duration}
                    onChange={(value) => {
                        partialSetWorkflowActionConfig(action.id, { max_wait_duration: value })
                    }}
                />
            </div>

            <div className="flex flex-col gap-1">
                <LemonLabel>Event to wait for</LemonLabel>
                <LemonInput
                    value={localEventName || ''}
                    onChange={handleNameChange}
                    placeholder="When event matches"
                    size="small"
                />
                <HogFlowPropertyFilters
                    filtersKey={`wait-for-event-${action.id}`}
                    filters={event_filters.filters ?? {}}
                    setFilters={(filters) =>
                        partialSetWorkflowActionConfig(action.id, { event_filters: { ...event_filters, filters } })
                    }
                    typeKey="workflow-wait-for-event"
                />
            </div>
        </>
    )
}

