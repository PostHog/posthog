import { IconPlus } from '@posthog/icons'
import { Handle, useUpdateNodeInternals } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { getHogFlowStep } from './HogFlowSteps'
import { HogFlowStepNodeProps } from './types'
import { NODE_HEIGHT, NODE_WIDTH } from '../constants'

export type ReactFlowNodeType = HogFlowAction['type'] | 'dropzone'

export const REACT_FLOW_NODE_TYPES: Record<ReactFlowNodeType, React.ComponentType<HogFlowStepNodeProps>> = {
    dropzone: DropzoneNode,
    // Everything else is a HogFlowActionNode
    trigger: HogFlowActionNode,
    function: HogFlowActionNode,
    function_email: HogFlowActionNode,
    function_sms: HogFlowActionNode,
    function_webhook: HogFlowActionNode,
    function_slack: HogFlowActionNode,
    conditional_branch: HogFlowActionNode,
    delay: HogFlowActionNode,
    wait_until_condition: HogFlowActionNode,
    exit: HogFlowActionNode,
    random_cohort_branch: HogFlowActionNode,
    wait_until_time_window: HogFlowActionNode,
}

function DropzoneNode({ id }: HogFlowStepNodeProps): JSX.Element {
    const [isHighlighted, setIsHighlighted] = useState(false)
    const { setHighlightedDropzoneNodeId } = useActions(hogFlowEditorLogic)

    useEffect(() => {
        setHighlightedDropzoneNodeId(isHighlighted ? id : null)
    }, [id, isHighlighted, setHighlightedDropzoneNodeId])

    return (
        <div
            onDragOver={() => setIsHighlighted(true)}
            onDragLeave={() => setIsHighlighted(false)}
            className={clsx(
                'flex justify-center items-center p-2 rounded border border-dashed transition-all cursor-pointer',
                isHighlighted ? 'border-primary bg-surface-primary' : 'border-transparent'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
            }}
        >
            <div className="flex flex-col justify-center items-center w-4 h-4 rounded-full border bg-surface-primary">
                <IconPlus className="text-sm text-primary" />
            </div>
        </div>
    )
}

function HogFlowActionNode(props: HogFlowStepNodeProps): JSX.Element | null {
    const updateNodeInternals = useUpdateNodeInternals()

    const { nodesById } = useValues(hogFlowEditorLogic)

    useEffect(() => {
        updateNodeInternals(props.id)
    }, [props.id, updateNodeInternals])

    const Step = getHogFlowStep(props.data.type)

    const node = nodesById[props.id]

    return (
        <>
            {node?.handles?.map((handle) => (
                // isConnectable={false} prevents edges from being manually added
                <Handle key={handle.id} className="opacity-0" {...handle} isConnectable={false} />
            ))}
            {Step?.renderNode(props) || <StepView action={props.data} />}
        </>
    )
}
