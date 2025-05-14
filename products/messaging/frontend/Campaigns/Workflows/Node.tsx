import { IconBolt, IconDecisionTree, IconHourglass, IconLeave, IconPlus, IconSend } from '@posthog/icons'
import { WorkflowNode } from '@posthog/workflows'
import { Handle, Position } from '@xyflow/react'

export const REACT_FLOW_NODE_TYPES = {
    addIcon: AddIconNode,
    trigger: TriggerNode,
    message: MessageNode,
    condition: ConditionNode,
    delay: DelayNode,
    exit: ExitNode,
}

interface NodeProps {
    children?: React.ReactNode
    icon?: React.ReactNode
    data: WorkflowNode['data']
}

function BaseNode({ icon, data, children }: NodeProps): JSX.Element {
    return (
        <div className="bg-surface-primary border rounded p-2 cursor-grab hover:bg-surface-secondary transition-colors">
            <div className="flex items-center gap-1">
                {icon}
                <div className="text-xs">{data.label}</div>
            </div>
            {children}
        </div>
    )
}

function TriggerNode({ data }: NodeProps): JSX.Element {
    return (
        <BaseNode data={data} icon={<IconBolt />}>
            <Handle type="source" position={Position.Bottom} />
        </BaseNode>
    )
}

function MessageNode({ data }: NodeProps): JSX.Element {
    return (
        <BaseNode data={data} icon={<IconSend />}>
            <Handle type="target" position={Position.Top} />
            <Handle type="source" position={Position.Bottom} />
        </BaseNode>
    )
}

function ConditionNode({ data }: NodeProps): JSX.Element {
    return (
        <BaseNode icon={<IconDecisionTree />} data={data}>
            <Handle type="target" position={Position.Top} />
            {/* Need a source handle for every condition */}
            <Handle type="source" position={Position.Bottom} />
            <Handle type="source" position={Position.Bottom} />
            <Handle type="source" position={Position.Bottom} />
        </BaseNode>
    )
}

function DelayNode({ data }: NodeProps): JSX.Element {
    return (
        <BaseNode data={data} icon={<IconHourglass />}>
            <Handle type="target" position={Position.Top} />
            <Handle type="source" position={Position.Bottom} />
        </BaseNode>
    )
}

function ExitNode({ data }: NodeProps): JSX.Element {
    return (
        <BaseNode data={data} icon={<IconLeave />}>
            <Handle type="target" position={Position.Top} />
        </BaseNode>
    )
}

function AddIconNode(): JSX.Element {
    return <IconPlus />
}
