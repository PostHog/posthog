import { Handle, Node, useUpdateNodeInternals } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlus } from '@posthog/icons'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowAction } from '../types'
import { getHogFlowStep } from './HogFlowSteps'
import { StepView } from './components/StepView'
import { HogFlowStepNodeProps, StepViewNodeHandle } from './types'

export type ReactFlowNodeType = HogFlowAction['type'] | 'dropzone'

export const DROPZONE_NODE_WIDTH = 100
export const DROPZONE_NODE_HEIGHT = 34

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
                'flex cursor-pointer items-center justify-center rounded border border-dashed p-2 transition-all',
                isHighlighted ? 'border-primary bg-surface-primary' : 'border-transparent'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: DROPZONE_NODE_WIDTH,
                height: DROPZONE_NODE_HEIGHT,
            }}
        >
            <div className="bg-surface-primary flex h-4 w-4 flex-col items-center justify-center rounded-full border">
                <IconPlus className="text-primary text-sm" />
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
                <StepView action={props.data} name={`Error: ${props.data.type} not implemented`} />
            )}
        </>
    )
}
