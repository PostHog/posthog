import { IconLeave } from '@posthog/icons'
import { Node, Position } from '@xyflow/react'

import { TOP_HANDLE_POSITION } from '../constants'
import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepExit: HogFlowStep<'exit'> = {
    type: 'exit',
    renderNode: (props) => <StepExitNode {...props} />,
    renderConfiguration: (node) => <StepExitConfiguration node={node} />,
    create: () => {
        return {
            name: 'Exit',
            description: '',
            type: 'exit',
            config: {
                reason: 'user_exited',
            },
        }
    },
    getHandles(action) {
        return [
            {
                id: `target_${action.id}`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
        ]
    },
}

function StepExitNode({ data }: HogFlowStepNodeProps): JSX.Element {
    // TODO: Use node data to render trigger node
    return (
        <StepView
            name={data.name}
            icon={<IconLeave className="text-green-400" />}
            selected={false}
            handles={StepExit.getHandles(data)}
        />
    )
}

function StepExitConfiguration({ node }: { node: Node<Extract<HogFlowAction, { type: 'exit' }>> }): JSX.Element {
    return (
        <>
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Exit</p>
            </div>
        </>
    )
}
