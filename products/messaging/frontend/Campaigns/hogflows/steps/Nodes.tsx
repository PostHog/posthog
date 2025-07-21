import { Handle, useNodeConnections, useUpdateNodeInternals } from '@xyflow/react'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { StepView } from './components/StepView'
import { getHogFlowStep } from './HogFlowSteps'
import type { HogFlowStepNodeProps, StepViewNodeHandle } from './types'
import type { HogFlowAction, HogFlowActionNode } from '../types'
import { useValues } from 'kea'
import { useEffect } from 'react'
export type ReactFlowNodeType = HogFlowAction['type']

export const REACT_FLOW_NODE_TYPES: Record<ReactFlowNodeType, React.ComponentType<HogFlowStepNodeProps>> = {
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
            className="flex justify-center items-center rounded border-secondary transition-all cursor-pointer bg-surface-primary hover:bg-surface-secondary"
        />
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
                <HogFlowActionNodeHandle key={handle.id} handle={handle} node={node} />
            ))}
            {Step?.renderNode(props) || <StepView action={props.data} />}
        </>
    )
}
