import {
    IconBolt,
    IconCode,
    IconDecisionTree,
    IconHourglass,
    IconLeave,
    IconPlus,
    IconRandom,
    IconRevert,
    IconSend,
} from '@posthog/icons'
import { Handle, useUpdateNodeInternals } from '@xyflow/react'
import { useActions } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlowAction } from '../types'
import { HogFlowActionManager } from './hogFlowActionManager'

// Import the NodeHandle type from the manager
type NodeHandle = Omit<Handle, 'width' | 'height' | 'nodeId'> & { label?: string }

export type ReactFlowNodeType = HogFlowAction['type'] | 'dropzone'

export const REACT_FLOW_NODE_TYPES: Record<ReactFlowNodeType, React.ComponentType<NodeProps>> = {
    dropzone: DropzoneNode,
    trigger: TriggerNode,
    message: EmailNode,
    conditional_branch: ConditionNode,
    delay: DelayNode,
    wait_until_condition: DelayUntilNode,
    exit: ExitNode,
    random_cohort_branch: RandomCohortBranchNode,
    wait_until_time_window: WaitUntilTimeWindowNode,
    function: FunctionNode,
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
    }, [isHighlighted, setHighlightedDropzoneNodeId])

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

function BaseNode({ id, icon, selected, data, children }: NodeProps): JSX.Element {
    const updateNodeInternals = useUpdateNodeInternals()
    const hogFlowAction = useMemo(() => HogFlowActionManager.fromAction(data), [data])

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
            <div className="flex gap-1 justify-center items-center">
                {icon}
                <div className="text-xs">{data.name}</div>
            </div>
            {children}
            {hogFlowAction.getHandles()?.map((handle: NodeHandle) => (
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

function RandomCohortBranchNode(props: NodeProps): JSX.Element {
    return <BaseNode {...props} icon={<IconRandom className="text-muted" />} />
}

function WaitUntilTimeWindowNode(props: NodeProps): JSX.Element {
    return <BaseNode {...props} icon={<IconHourglass className="text-muted" />} />
}

function FunctionNode(props: NodeProps): JSX.Element {
    return <BaseNode {...props} icon={<IconCode className="text-muted" />} />
}

function ExitNode(props: NodeProps): JSX.Element {
    return <BaseNode {...props} icon={<IconLeave className="text-red-500" />} />
}
