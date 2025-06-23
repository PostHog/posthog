import { IconDecisionTree } from '@posthog/icons'
import { Node, Position } from '@xyflow/react'
import { useActions } from 'kea'

import { LEFT_HANDLE_POSITION, RIGHT_HANDLE_POSITION, TOP_HANDLE_POSITION } from '../constants'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepWaitUntilCondition: HogFlowStep<'wait_until_condition'> = {
    type: 'wait_until_condition',
    renderNode: (props) => <StepWaitUntilConditionNode {...props} />,
    renderConfiguration: (node) => <StepWaitUntilConditionConfiguration node={node} />,
    create: (edgeToInsertNodeInto) => {
        return {
            name: 'Wait until...',
            description: '',
            type: 'wait_until_condition',
            on_error: 'continue',
            config: {
                condition: { filter: null },
                max_wait_duration: '300s',
            },
            next_actions: {
                continue: {
                    action_id: edgeToInsertNodeInto.target,
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

function StepWaitUntilConditionNode({ data }: HogFlowStepNodeProps): JSX.Element {
    // TODO: Use node data to render trigger node
    return (
        <StepView
            name={data.name}
            icon={<IconDecisionTree className="text-green-400" />}
            selected={false}
            handles={StepWaitUntilCondition.getHandles(data)}
        />
    )
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
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Wait until...</p>
                <p className="mb-0">Wait until a condition is met.</p>
            </div>
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Condition</p>
                <p className="mb-0">Choose which events or actions will enter a user into the campaign.</p>
            </div>
        </>
    )
}
