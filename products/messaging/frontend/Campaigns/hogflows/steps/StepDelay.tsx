import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { IconClock } from '@posthog/icons'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { HogFlowStep } from './types'

export const StepDelay: HogFlowStep<'delay'> = {
    type: 'delay',
    name: 'Delay',
    description: 'Wait for a specified duration.',
    icon: <IconClock className="text-[#a20031]" />,
    color: '#a20031',
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
