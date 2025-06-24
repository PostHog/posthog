import { IconLeave } from '@posthog/icons'
import { Node } from '@xyflow/react'

import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepExit: HogFlowStep<'exit'> = {
    type: 'exit',
    name: 'Exit',
    description: 'Exit the campaign.',
    icon: <IconLeave />,
    renderNode: (props) => <StepExitNode {...props} />,
    renderConfiguration: (node) => <StepExitConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Exit',
                description: '',
                type: 'exit',
                config: {
                    reason: 'user_exited',
                },
            },
        }
    },
}

function StepExitNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView action={data} />
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function StepExitConfiguration(_: { node: Node<Extract<HogFlowAction, { type: 'exit' }>> }): JSX.Element {
    return (
        <>
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Exit</p>
            </div>
        </>
    )
}
