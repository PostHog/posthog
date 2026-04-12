import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowEventFilters } from '../filters/HogFlowFilters'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'

type WaitUntilEventAction = Extract<HogFlowAction, { type: 'wait_until_event' }>

export function StepWaitUntilEventConfiguration({ node }: { node: Node<WaitUntilEventAction> }): JSX.Element {
    const action = node.data
    const { events, max_wait_duration } = action.config

    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    // All events live in a single filters object (events[0].filters),
    // matching the trigger's flat event list pattern. Each event is a
    // row managed by HogFlowEventFilters / ActionFilter.
    const filters = events[0]?.filters ?? {}

    return (
        <>
            <StepSchemaErrors />

            <div className="text-xs text-muted">
                Pause until any of the configured events fire for the user, or until the timeout. The matched path is
                taken on event arrival; the timeout path is taken if no event arrives in time. This is different from
                "Wait until condition", which only re-checks person properties on a polling schedule.
            </div>

            <HogFlowEventFilters
                filtersKey={`wait-until-event-${action.id}`}
                filters={filters}
                setFilters={(newFilters) =>
                    partialSetWorkflowActionConfig(action.id, {
                        events: [{ filters: newFilters ?? {} }],
                    })
                }
                typeKey="workflow-wait-until-event"
                buttonCopy="Add event"
            />

            <div className="flex flex-col gap-1">
                <LemonLabel>Max time to wait for event</LemonLabel>
                <HogFlowDuration
                    value={max_wait_duration}
                    onChange={(value) => {
                        partialSetWorkflowActionConfig(action.id, { max_wait_duration: value })
                    }}
                />
            </div>
        </>
    )
}
