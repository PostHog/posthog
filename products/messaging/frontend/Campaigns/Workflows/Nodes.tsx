import { IconBolt, IconDecisionTree, IconHourglass, IconLeave, IconPlus, IconRevert, IconSend } from '@posthog/icons'
import { WorkflowNode } from '@posthog/workflows'
import { Handle, Position } from '@xyflow/react'

export const REACT_FLOW_NODE_TYPES = {
    dropzone: DropzoneNode,
    dropzone_highlighted: DropzoneNode,
    trigger: TriggerNode,
    email: EmailNode,
    condition: ConditionNode,
    delay: DelayNode,
    delay_until: DelayUntilNode,
    exit: ExitNode,
}
interface NodeProps {
    children?: React.ReactNode
    icon?: React.ReactNode
    selected?: boolean
    type?: string
    data: WorkflowNode['data']
}

function DropzoneNode({ type }: NodeProps): JSX.Element {
    return (
        <div
            className={`w-[100px] h-[34px] bg-surface-secondary border ${
                type === 'dropzone_highlighted' ? 'border-secondary bg-surface-primary' : 'border-primary'
            } border-dashed rounded p-2 cursor-pointer`}
        >
            <div className="flex items-center justify-center gap-1">
                <IconPlus />
            </div>
            <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
            <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
        </div>
    )
}

function BaseNode({ icon, selected, data, children }: NodeProps): JSX.Element {
    return (
        <div
            className={`w-[100px] h-[34px] bg-surface-primary border ${
                selected ? 'border-secondary' : 'border-primary'
            } rounded p-2 hover:bg-surface-secondary transition-transform duration-300 cursor-pointer`}
        >
            <div className="flex items-center justify-center gap-1">
                {icon}
                <div className="text-xs">{data.label}</div>
            </div>
            {children}
        </div>
    )
}

function TriggerNode(props: NodeProps): JSX.Element {
    return (
        <BaseNode {...props} icon={<IconBolt className="text-green-300" />}>
            <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
        </BaseNode>
    )
}

function EmailNode(props: NodeProps): JSX.Element {
    return (
        <BaseNode {...props} icon={<IconSend className="text-muted" />}>
            <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
            <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
        </BaseNode>
    )
}

function ConditionNode(props: NodeProps): JSX.Element {
    return (
        <BaseNode {...props} icon={<IconDecisionTree className="text-muted" />}>
            <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
            <Handle id="on_condition_match_0" type="source" position={Position.Bottom} style={{ opacity: 0 }} />
            <Handle id="on_error" type="source" position={Position.Bottom} style={{ opacity: 0 }} />
        </BaseNode>
    )
}

function DelayNode(props: NodeProps): JSX.Element {
    return (
        <BaseNode {...props} icon={<IconHourglass className="text-muted" />}>
            <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
            <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
        </BaseNode>
    )
}

function DelayUntilNode(props: NodeProps): JSX.Element {
    return (
        <BaseNode {...props} icon={<IconRevert className="text-muted" />}>
            <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
            <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
        </BaseNode>
    )
}

function ExitNode(props: NodeProps): JSX.Element {
    return (
        <BaseNode {...props} icon={<IconLeave className="text-red-500" />}>
            <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
        </BaseNode>
    )
}
