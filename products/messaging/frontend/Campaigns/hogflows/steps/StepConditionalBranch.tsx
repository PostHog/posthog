import { IconDecisionTree } from '@posthog/icons'
import { Node, Position } from '@xyflow/react'
import { useActions } from 'kea'

import { LEFT_HANDLE_POSITION, RIGHT_HANDLE_POSITION, TOP_HANDLE_POSITION } from '../constants'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepConditionalBranch: HogFlowStep<'conditional_branch'> = {
    type: 'conditional_branch',
    renderNode: (props) => <StepConditionalBranchNode {...props} />,
    renderConfiguration: (node) => <StepConditionalBranchConfiguration node={node} />,
    create: (edgeToInsertNodeInto) => {
        return {
            name: 'Conditional Branch',
            description: '',
            type: 'conditional_branch',
            on_error: 'continue',
            config: {
                conditions: [],
            },
            next_actions: {
                condition_0: {
                    action_id: edgeToInsertNodeInto.target,
                    label: 'Match condition 1',
                },
                continue: {
                    action_id: edgeToInsertNodeInto.target,
                    label: 'No match',
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
                id: `condition_0_${action.id}`,
                type: 'source',
                position: Position.Left,
                ...LEFT_HANDLE_POSITION,
            },
            {
                id: `continue_${action.id}`,
                type: 'source',
                position: Position.Right,
                ...RIGHT_HANDLE_POSITION,
            },
        ]
    },
}

function StepConditionalBranchNode({ data }: HogFlowStepNodeProps): JSX.Element {
    // TODO: Use node data to render trigger node
    return (
        <StepView
            name={data.name}
            icon={<IconDecisionTree className="text-green-400" />}
            selected={false}
            handles={StepConditionalBranch.getHandles(data)}
        />
    )
}

function StepConditionalBranchConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'conditional_branch' }>>
}): JSX.Element {
    const action = node.data
    const { conditions } = action.config

    const { setCampaignActionConfig } = useActions(hogFlowEditorLogic)

    return (
        <>
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Conditional Branch</p>
                <p className="mb-0">Choose which events or actions will enter a user into the campaign.</p>
            </div>
        </>
    )
}
