import { IconBolt } from '@posthog/icons'
import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { HogFlowFilters } from '../filters/HogFlowFilters'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepTrigger: HogFlowStep<'trigger'> = {
    type: 'trigger',
    name: 'Trigger',
    description: 'Trigger the campaign.',
    icon: <IconBolt />,
    renderNode: (props) => <StepTriggerNode {...props} />,
    renderConfiguration: (node) => <StepTriggerConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Trigger',
                description: '',
                type: 'trigger',
                config: {
                    type: 'event',
                },
            },
        }
    },
}

function StepTriggerNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView action={data} />
}

function StepTriggerConfiguration({ node }: { node: Node<Extract<HogFlowAction, { type: 'trigger' }>> }): JSX.Element {
    const action = node.data
    const { filters } = action.config

    const { setCampaignActionConfig } = useActions(hogFlowEditorLogic)

    return (
        <>
            <div className="flex flex-col">
                <p className="mb-0">Choose which events or actions will enter a user into the campaign.</p>
            </div>
            <HogFlowFilters
                filters={filters ?? {}}
                setFilters={(filters) => setCampaignActionConfig(action.id, { filters })}
                typeKey="campaign-trigger"
                buttonCopy="Add trigger event"
            />
        </>
    )
}
