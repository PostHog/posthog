import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { IconCursor, IconPerson } from '@posthog/icons'
import { LemonDivider, LemonLabel } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowEventFilters, HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { useDebouncedNameInput } from './utils'

export function StepWaitUntilConditionConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'wait_until_condition' }>>
}): JSX.Element {
    const action = node.data
    const { condition, events, max_wait_duration } = action.config

    const { partialSetWorkflowActionConfig } = useActions(workflowLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const waitUntilEventEnabled = !!featureFlags[FEATURE_FLAGS.WORKFLOWS_WAIT_UNTIL_EVENT]

    const { localName: localConditionName, handleNameChange } = useDebouncedNameInput(condition, (updatedCondition) =>
        partialSetWorkflowActionConfig(action.id, { condition: updatedCondition })
    )

    const eventFilters = events?.[0]?.filters ?? {}

    return (
        <>
            <StepSchemaErrors />

            {waitUntilEventEnabled && (
                <>
                    <div className="flex flex-col gap-3">
                        <span className="flex gap-1">
                            <IconCursor className="text-lg" />
                            <span className="text-md font-semibold">Events to wait for</span>
                        </span>
                        <span className="text-xs text-muted">
                            The workflow continues on the matched path when any of these events fire.
                        </span>
                        <HogFlowEventFilters
                            filtersKey={`wait-until-events-${action.id}`}
                            filters={eventFilters}
                            setFilters={(newFilters) =>
                                partialSetWorkflowActionConfig(action.id, {
                                    events: newFilters ? [{ filters: newFilters }] : undefined,
                                })
                            }
                            typeKey="workflow-wait-until-event"
                            buttonCopy="Add event"
                        />
                    </div>

                    <div className="flex items-center gap-4 my-2">
                        <div className="flex-1 border-t border-border" />
                        <span className="text-xs text-tertiary uppercase tracking-wide">or</span>
                        <div className="flex-1 border-t border-border" />
                    </div>
                </>
            )}

            <div className="flex flex-col gap-3">
                {waitUntilEventEnabled ? (
                    <>
                        <span className="flex gap-1">
                            <IconPerson className="text-lg" />
                            <span className="text-md font-semibold">Property conditions</span>
                        </span>
                        <span className="text-xs text-muted">
                            The workflow continues when the person matches these properties.
                        </span>
                    </>
                ) : (
                    <LemonLabel>Conditions to wait for</LemonLabel>
                )}
                <LemonInput
                    value={localConditionName || ''}
                    onChange={handleNameChange}
                    placeholder="If condition matches"
                    size="small"
                />
                <HogFlowPropertyFilters
                    filtersKey={`wait-until-condition-${action.id}`}
                    filters={condition.filters ?? {}}
                    setFilters={(filters) =>
                        partialSetWorkflowActionConfig(action.id, { condition: { ...condition, filters } })
                    }
                    typeKey="workflow-wait-until-condition"
                />
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-1">
                <LemonLabel>Max time to wait</LemonLabel>
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
