import { IconBolt, IconDecisionTree, IconHourglass, IconLeave, IconPlus, IconSend } from '@posthog/icons'
import { WorkflowNode } from '@posthog/workflows'
import { Handle, Position } from '@xyflow/react'
import AddEdge from './Edges'

export const REACT_FLOW_NODE_TYPES = {
    addIcon: AddIconNode,
    trigger: TriggerNode,
    email: EmailNode,
    condition: ConditionNode,
    delay: DelayNode,
    exit: ExitNode,
}

export const REACT_FLOW_EDGE_TYPES = {
    add: AddEdge,
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
            <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
        </BaseNode>
    )
}

function EmailNode({ data }: NodeProps): JSX.Element {
    return (
        <BaseNode data={data} icon={<IconSend />}>
            <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
            <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
        </BaseNode>
    )
}

function ConditionNode({ data }: NodeProps): JSX.Element {
    return (
        <BaseNode icon={<IconDecisionTree />} data={data}>
            <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
            <Handle type="source" position={Position.Bottom} id="true" style={{ opacity: 0 }} />
            <Handle
                type="source"
                position={Position.Bottom}
                id="false"
                style={{ opacity: 0, left: 'auto', right: 0 }}
            />
        </BaseNode>
    )
}

function DelayNode({ data }: NodeProps): JSX.Element {
    return (
        <BaseNode data={data} icon={<IconHourglass />}>
            <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
            <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
        </BaseNode>
    )
}

function ExitNode({ data }: NodeProps): JSX.Element {
    return (
        <BaseNode data={data} icon={<IconLeave />}>
            <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
        </BaseNode>
    )
}

function AddIconNode(): JSX.Element {
    return (
        <div className="bg-surface-primary border border-primary rounded-full w-8 h-8 flex items-center justify-center">
            <IconPlus className="text-primary" />
            <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
            <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
        </div>
    )
}
