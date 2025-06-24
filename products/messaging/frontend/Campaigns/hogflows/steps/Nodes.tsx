import { IconPlus } from '@posthog/icons'
import { Handle, Node, useUpdateNodeInternals } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { getHogFlowStep } from './HogFlowSteps'
import { HogFlowStepNodeProps, StepViewNodeHandle } from './types'

export type ReactFlowNodeType = HogFlowAction['type'] | 'dropzone'

export const REACT_FLOW_NODE_TYPES: Record<ReactFlowNodeType, React.ComponentType<HogFlowStepNodeProps>> = {
    dropzone: DropzoneNode,
    // Everything else is a HogFlowActionNode
    trigger: HogFlowActionNode,
    message: HogFlowActionNode,
    conditional_branch: HogFlowActionNode,
    delay: HogFlowActionNode,
    wait_until_condition: HogFlowActionNode,
    exit: HogFlowActionNode,
    random_cohort_branch: HogFlowActionNode,
    wait_until_time_window: HogFlowActionNode,
    function: HogFlowActionNode,
}

interface NodeProps {
    id: string
    children?: React.ReactNode
    icon?: React.ReactNode
    selected?: boolean
    type?: string
    data: HogFlowAction
}

function DropzoneNode({ id }: NodeProps): JSX.Element {
    const [isHighlighted, setIsHighlighted] = useState(false)
    const { setHighlightedDropzoneNodeId } = useActions(hogFlowEditorLogic)

    useEffect(() => {
        setHighlightedDropzoneNodeId(isHighlighted ? id : null)
    }, [id, isHighlighted, setHighlightedDropzoneNodeId])

    return (
        <div
            onDragOver={() => setIsHighlighted(true)}
            onDragLeave={() => setIsHighlighted(false)}
            className={`w-[100px] h-[34px] bg-surface-secondary border ${
                isHighlighted ? 'border-secondary bg-surface-primary' : 'border-primary'
            } border-dashed rounded p-2 cursor-pointer`}
        >
            <div className="flex gap-1 justify-center items-center">
                <IconPlus />
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

    const getHandleStyle = (handle: StepViewNodeHandle, node: Node): React.CSSProperties | undefined => {
        if (handle.type === 'source') {
            const sourceHandles = node.handles?.filter((h: any) => h.type === 'source') || []
            const sourceHandleIndex = sourceHandles.findIndex((h: any) => h.id === handle.id)
            const numSourceHandles = sourceHandles.length
            return {
                // Spread out outgoing ports evenly along bottom of nodes
                left: `${((sourceHandleIndex + 1) / (numSourceHandles + 1)) * 100}%`,
            }
        }
        return undefined
    }

    return (
        <>
            {node?.handles?.map((handle) => (
                // isConnectable={false} prevents edges from being manually added
                <Handle
                    key={handle.id}
                    className="opacity-0"
                    {...handle}
                    isConnectable={false}
                    style={getHandleStyle(handle, node)}
                />
            ))}
            {Step?.renderNode(props) || (
                <StepView name={`Error: ${props.data.type} not implemented`} selected={false} />
            )}
        </>
    )
}
