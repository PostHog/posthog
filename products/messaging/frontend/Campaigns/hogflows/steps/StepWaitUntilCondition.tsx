import { IconClock } from '@posthog/icons'
import { LemonLabel } from '@posthog/lemon-ui'
import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { HogFlowFilters } from '../filters/HogFlowFilters'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepWaitUntilCondition: HogFlowStep<'wait_until_condition'> = {
    type: 'wait_until_condition',
    name: 'Wait until...',
    description: 'Wait until a condition is met or a duration has passed.',
    icon: <IconClock />,
    renderNode: (props) => <StepWaitUntilConditionNode {...props} />,
    renderConfiguration: (node) => <StepWaitUntilConditionConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Wait until...',
                description: '',
                type: 'wait_until_condition',
                on_error: 'continue',
                config: {
                    condition: { filters: null },
                    max_wait_duration: '5m',
                },
            },
            branchEdges: 1,
        }
    },
}

function StepWaitUntilConditionNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView action={data} />
}

function StepWaitUntilConditionConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'wait_until_condition' }>>
}): JSX.Element {
    const action = node.data
    const { condition, max_wait_duration } = action.config

    const { setCampaignActionConfig } = useActions(hogFlowEditorLogic)

    return (
        <>
            <div>
                <LemonLabel>Wait time</LemonLabel>
                <HogFlowDuration
                    value={max_wait_duration}
                    onChange={(value) => {
                        setCampaignActionConfig(action.id, { max_wait_duration: value })
                    }}
                />
            </div>

            <div>
                <LemonLabel>Conditions to wait for</LemonLabel>
                <HogFlowFilters
                    filters={condition.filters ?? {}}
                    setFilters={(filters) => setCampaignActionConfig(action.id, { condition: { filters } })}
                    typeKey="campaign-wait-until-condition"
                />
            </div>
        </>
    )
}
