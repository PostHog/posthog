import { IconDecisionTree } from '@posthog/icons'
import { Node, Position } from '@xyflow/react'
import { useActions } from 'kea'

import { LEFT_HANDLE_POSITION, RIGHT_HANDLE_POSITION, TOP_HANDLE_POSITION } from '../constants'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepDelay: HogFlowStep<'delay'> = {
    type: 'delay',
    renderNode: (props) => <StepDelayNode {...props} />,
    renderConfiguration: (node) => <StepDelayConfiguration node={node} />,
    create: (edgeToInsertNodeInto) => {
        return {
            name: 'Wait',
            description: '',
            type: 'delay',
            on_error: 'continue',
            config: {
                delay_duration: '10m',
            },
            next_actions: {
                continue: {
                    action_id: edgeToInsertNodeInto.target,
                    label: 'Continue',
                },
            },
        }
    },
    // TODO: Can we derive handles from the next_actions instead?
    getHandles(action) {
        return [
            {
                id: `target_${action.id}`,
                type: 'target',
                position: Position.Top,
                ...TOP_HANDLE_POSITION,
            },
            {
                id: `continue_${action.id}`,
                type: 'source',
                position: Position.Left,
                ...LEFT_HANDLE_POSITION,
            },
            {
                id: `abort_${action.id}`,
                type: 'source',
                position: Position.Right,
                ...RIGHT_HANDLE_POSITION,
            },
        ]
    },
}

function StepDelayNode({ data }: HogFlowStepNodeProps): JSX.Element {
    // TODO: Use node data to render trigger node
    return (
        <StepView
            name={data.name}
            icon={<IconDecisionTree className="text-green-400" />}
            selected={false}
            handles={StepDelay.getHandles(data)}
        />
    )
}

function StepDelayConfiguration({ node }: { node: Node<Extract<HogFlowAction, { type: 'delay' }>> }): JSX.Element {
    const action = node.data
    const { delay_duration } = action.config

    const { setCampaignActionConfig } = useActions(hogFlowEditorLogic)

    return (
        <>
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Wait</p>
                <p className="mb-0">Wait for a specified duration.</p>
            </div>
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Duration</p>
                <p className="mb-0">Choose which events or actions will enter a user into the campaign.</p>
            </div>
        </>
    )
}
