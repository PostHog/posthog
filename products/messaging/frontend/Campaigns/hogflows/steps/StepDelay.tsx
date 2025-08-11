import { IconClock } from '@posthog/icons'
import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepDelay: HogFlowStep<'delay'> = {
    type: 'delay',
    name: 'Delay',
    description: 'Wait for a specified duration.',
    icon: <IconClock className="text-[#a20031]" />,
    color: '#a20031',
    renderNode: (props) => <StepDelayNode {...props} />,
    renderConfiguration: (node) => <StepDelayConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Delay',
                description: '',
                type: 'delay',
                on_error: 'continue',
                config: {
                    delay_duration: '10m',
                },
            },
        }
    },
}

function StepDelayNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView action={data} />
}

function StepDelayConfiguration({ node }: { node: Node<Extract<HogFlowAction, { type: 'delay' }>> }): JSX.Element {
    const action = node.data
    const { delay_duration } = action.config

    const { setCampaignActionConfig } = useActions(hogFlowEditorLogic)

    return (
        <>
            <p className="mb-0">Wait for a specified duration.</p>
            <HogFlowDuration
                value={delay_duration}
                onChange={(value) => setCampaignActionConfig(action.id, { delay_duration: value })}
            />
        </>
    )
}
