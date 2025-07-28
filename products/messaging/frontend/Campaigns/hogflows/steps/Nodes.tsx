import { Handle, useNodeConnections, useUpdateNodeInternals } from '@xyflow/react'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { StepView } from './components/StepView'
import { getHogFlowStep } from './HogFlowSteps'
import type { HogFlowStepNodeProps, StepViewNodeHandle } from './types'
import type { HogFlowAction, HogFlowActionNode } from '../types'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import clsx from 'clsx'
import { IconPlus, IconX } from '@posthog/icons'
import { DROPZONE_NODE_WIDTH, NODE_HEIGHT } from '../constants'

export type ReactFlowNodeType = HogFlowAction['type'] | 'dropzone' | 'edge_deletion_button'

export const REACT_FLOW_NODE_TYPES: Record<ReactFlowNodeType, React.ComponentType<HogFlowStepNodeProps>> = {
    dropzone: DropzoneNode,
    edge_deletion_button: EdgeDeletionButtonNode, // Special node for edge deletion button
    // Everything else is a HogFlowActionNode
    trigger: HogFlowActionNode,
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
    const { highlightedDropzoneNodeId } = useValues(hogFlowEditorLogic)
    const [isHighlighted, setIsHighlighted] = useState(highlightedDropzoneNodeId === id)
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
                width: DROPZONE_NODE_WIDTH,
                height: NODE_HEIGHT,
            }}
        >
            <div className="flex flex-col justify-center items-center w-4 h-4 rounded-full border bg-surface-primary">
                <IconPlus className="text-sm text-primary" />
            </div>
        </div>
    )
}

function EdgeDeletionButtonNode(): JSX.Element {
    const { deleteSelectedEdge } = useActions(hogFlowEditorLogic)

    return (
        <div
            className="flex flex-col justify-center items-center w-4 h-4 rounded-full border bg-surface-primary cursor-pointer hover:bg-surface-secondary transition-all"
            onClick={(e) => {
                e.stopPropagation()
                deleteSelectedEdge()
            }}
        >
            <IconX className="text-xs text-muted" />
        </div>
    )
}

function HogFlowActionNodeHandle({
    handle,
    node,
}: {
    handle: StepViewNodeHandle
    node: HogFlowActionNode
}): JSX.Element {
    const connections = useNodeConnections({
        handleType: handle.type,
    })

    const getHandlePosition = (
        handle: StepViewNodeHandle,
        node: HogFlowActionNode
    ): React.CSSProperties | undefined => {
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
        <Handle
            key={handle.id}
            {...handle}
            // A single source handle can only connect to one edge per handle at a time, but target handles can have multiple connections
            isConnectable={handle.type === 'source' ? connections.length !== (node.handles?.length || 0) : true}
            isConnectableStart={handle.type === 'source'}
            isConnectableEnd={handle.type === 'target'}
            style={getHandlePosition(handle, node)}
            className="w-[12px] h-[12px] flex justify-center items-center rounded border-secondary transition-all cursor-pointer bg-surface-primary hover:bg-surface-secondary"
        />
    )
}

function HogFlowActionNode(props: HogFlowStepNodeProps): JSX.Element | null {
    const updateNodeInternals = useUpdateNodeInternals()

    const { nodesById } = useValues(hogFlowEditorLogic)

    const Step = getHogFlowStep(props.data.type)

    const node = nodesById[props.id]

    // When handle count changes, we need to update the node internals so that edges are re-rendered at
    // the correct positions
    useEffect(() => {
        setTimeout(() => {
            updateNodeInternals(props.id)
        }, 100)
        // oxlint-disable-next-line exhaustive-deps
    }, [node?.handles?.length, updateNodeInternals, props.id])

    return (
        <>
            {node?.handles?.map((handle) => (
                <HogFlowActionNodeHandle key={handle.id} handle={handle} node={node} />
            ))}
            {Step?.renderNode(props) || <StepView action={props.data} />}
        </>
    )
}
