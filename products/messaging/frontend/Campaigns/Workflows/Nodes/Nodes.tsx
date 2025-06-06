import { IconBolt, IconDecisionTree, IconHourglass, IconLeave, IconPlus, IconRevert, IconSend } from '@posthog/icons'
import { Handle, useUpdateNodeInternals } from '@xyflow/react'
import { useEffect } from 'react'

import { WorkflowNode, WorkflowNodeType } from '../temporary_workflow_types_for_dev_to_be_deleted'
import { getNodeHandles } from './utils'

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

export const DROPZONE_NODE_TYPES = ['dropzone', 'dropzone_highlighted']

interface NodeProps {
    id: string
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
        </div>
    )
}

function BaseNode({ id, icon, selected, type, data, children }: NodeProps): JSX.Element {
    const updateNodeInternals = useUpdateNodeInternals()
    const handles = getNodeHandles(id, type as WorkflowNodeType)

    useEffect(() => {
        updateNodeInternals(id)
    }, [id, updateNodeInternals])

    return (
        <div
            // Keep in sync with NODE_WIDTH and NODE_HEIGHT (tailwind will not accept dynamic values)
            className={`w-[100px] h-[34px] bg-surface-primary border ${
                selected ? 'border-secondary' : 'border-primary'
            } rounded p-2 hover:bg-surface-secondary transition-transform duration-300 cursor-pointer`}
        >
            <div className="flex items-center justify-center gap-1">
                {icon}
                <div className="text-xs">{data.label}</div>
            </div>
            {children}
            {handles?.map((handle) => (
                // isConnectable={false} prevents edges from being manually added
                <Handle key={handle.id} {...handle} isConnectable={false} className="opacity-0" />
            ))}
        </div>
    )
}

function TriggerNode(props: NodeProps): JSX.Element {
    return <BaseNode {...props} icon={<IconBolt className="text-green-400" />} />
}

function EmailNode(props: NodeProps): JSX.Element {
    return <BaseNode {...props} icon={<IconSend className="text-muted" />} />
}

function ConditionNode(props: NodeProps): JSX.Element {
    return <BaseNode {...props} icon={<IconDecisionTree className="text-muted" />} />
}

function DelayNode(props: NodeProps): JSX.Element {
    return <BaseNode {...props} icon={<IconHourglass className="text-muted" />} />
}

function DelayUntilNode(props: NodeProps): JSX.Element {
    return <BaseNode {...props} icon={<IconRevert className="text-muted" />} />
}

function ExitNode(props: NodeProps): JSX.Element {
    return <BaseNode {...props} icon={<IconLeave className="text-red-500" />} />
}
