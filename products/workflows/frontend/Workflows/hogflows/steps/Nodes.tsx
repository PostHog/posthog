import { Handle, useUpdateNodeInternals } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCopy, IconPlus } from '@posthog/icons'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { NODE_HEIGHT, NODE_WIDTH } from '../react_flow_utils/constants'
import type { HogFlowActionNode } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStepNodeProps } from './types'

export type ReactFlowNodeType = 'action' | 'dropzone'

export const REACT_FLOW_NODE_TYPES: Record<ReactFlowNodeType, React.ComponentType<HogFlowStepNodeProps>> = {
    dropzone: DropzoneNode,
    action: HogFlowActionNode,
}

function DropzoneNode({ id }: HogFlowStepNodeProps): JSX.Element {
    const [isHighlighted, setIsHighlighted] = useState(false)
    const { isCopyingNode } = useValues(hogFlowEditorLogic)
    const { setHighlightedDropzoneNodeId, copyNodeToHighlightedDropzone } = useActions(hogFlowEditorLogic)

    useEffect(() => {
        setHighlightedDropzoneNodeId(isHighlighted ? id : null)
    }, [id, isHighlighted, setHighlightedDropzoneNodeId])

    return (
        <div
            onDragOver={() => setIsHighlighted(true)}
            onDragLeave={() => setIsHighlighted(false)}
            onMouseOver={() => setIsHighlighted(true)}
            onMouseOut={() => setIsHighlighted(false)}
            onClick={isCopyingNode ? () => copyNodeToHighlightedDropzone() : undefined}
            className={clsx(
                'flex justify-center items-center p-2 rounded border border-dashed transition-all cursor-pointer hover:border-primary hover:bg-surface-primary',
                isHighlighted ? 'border-primary bg-surface-primary' : 'border-transparent'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
            }}
        >
            <div className="flex flex-col justify-center items-center w-4 h-4 rounded-full border bg-surface-primary">
                {isCopyingNode ? (
                    <IconCopy className="text-sm text-primary" />
                ) : (
                    <IconPlus className="text-sm text-primary" />
                )}
            </div>
        </div>
    )
}

function HogFlowActionNode(props: HogFlowStepNodeProps): JSX.Element | null {
    const updateNodeInternals = useUpdateNodeInternals()

    const { nodesById, isCopyingNode, nodeToBeAdded } = useValues(hogFlowEditorLogic)

    useEffect(() => {
        updateNodeInternals(props.id)
    }, [props.id, updateNodeInternals])

    const node = nodesById[props.id]

    const shouldWiggleCopyingNode =
        isCopyingNode && nodeToBeAdded && 'id' in nodeToBeAdded && (nodeToBeAdded as HogFlowActionNode).id === props.id

    return (
        <div className={clsx('transition-all hover:translate-y-[-2px]', shouldWiggleCopyingNode && 'animate-bounce')}>
            {node?.handles?.map((handle) => (
                // isConnectable={false} prevents edges from being manually added
                <Handle key={handle.id} className="opacity-0" {...handle} isConnectable={false} />
            ))}
            <StepView action={props.data} />
        </div>
    )
}
