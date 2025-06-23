import { IconDecisionTree } from '@posthog/icons'
import { LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { Node, Position } from '@xyflow/react'
import { useActions } from 'kea'

import { BOTTOM_HANDLE_POSITION, TOP_HANDLE_POSITION } from '../constants'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

const DURATION_REGEX = /^(\d*\.?\d+)([dhm])$/

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
                position: Position.Bottom,
                ...BOTTOM_HANDLE_POSITION,
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

    const parts = delay_duration.match(DURATION_REGEX) ?? ['', '10', 'm']
    const [, value, unit] = parts

    const numberValue = parseFloat(value)

    return (
        <>
            <p className="mb-0">Wait for a specified duration.</p>
            <div className="flex gap-2">
                <LemonInput
                    type="number"
                    value={numberValue}
                    onChange={(value) => setCampaignActionConfig(action.id, { delay_duration: `${value}${unit}` })}
                />

                <LemonSelect
                    options={[
                        { label: 'Minute(s)', value: 'm' },
                        { label: 'Hour(s)', value: 'h' },
                        { label: 'Day(s)', value: 'd' },
                    ]}
                    value={unit}
                    onChange={(value) => setCampaignActionConfig(action.id, { delay_duration: `${value}${unit}` })}
                />
            </div>
        </>
    )
}
