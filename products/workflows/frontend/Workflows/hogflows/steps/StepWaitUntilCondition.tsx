import { Node } from '@xyflow/react'
import { useActions } from 'kea'
import { useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { LemonLabel } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'

export function StepWaitUntilConditionConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'wait_until_condition' }>>
}): JSX.Element {
    const action = node.data
    const { condition, max_wait_duration } = action.config

    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)

    // Local state for condition name to avoid input lag
    const [localConditionName, setLocalConditionName] = useState<string | undefined>(condition.name)

    // Update local state when condition changes from external sources
    useEffect(() => {
        setLocalConditionName(condition.name)
    }, [condition.name])

    // Debounced function to update condition name
    const debouncedUpdateConditionName = useDebouncedCallback((value: string | undefined) => {
        const updated = { ...condition }
        if (value) {
            updated.name = value
        } else {
            delete updated.name
        }
        partialSetWorkflowActionConfig(action.id, { condition: updated })
    }, 300)

    return (
        <>
            <StepSchemaErrors />

            <div>
                <LemonLabel>Wait time</LemonLabel>
                <HogFlowDuration
                    value={max_wait_duration}
                    onChange={(value) => {
                        partialSetWorkflowActionConfig(action.id, { max_wait_duration: value })
                    }}
                />
            </div>

            <div>
                <LemonLabel>Conditions to wait for</LemonLabel>
                <LemonInput
                    value={localConditionName || ''}
                    onChange={(value) => {
                        // Update local state immediately for responsive typing
                        setLocalConditionName(value)

                        // Debounced update to persist the name
                        debouncedUpdateConditionName(value)
                    }}
                    placeholder="If condition matches"
                    size="small"
                />
                <HogFlowPropertyFilters
                    actionId={action.id}
                    filters={condition.filters ?? {}}
                    setFilters={(filters) =>
                        partialSetWorkflowActionConfig(action.id, { condition: { ...condition, filters } })
                    }
                    typeKey="workflow-wait-until-condition"
                />
            </div>
        </>
    )
}
