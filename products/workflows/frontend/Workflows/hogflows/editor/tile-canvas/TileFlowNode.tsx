import { Handle, NodeProps, Position } from '@xyflow/react'

import { cn } from 'lib/utils/css-classes'

import { motionProps } from './motionProps'
import type { TileFlowNodeType } from './tileCanvasNodes'
import { TileStackNode } from './TileStackNode'
import { TileStepNode } from './TileStepNode'

export function TileFlowNode({ data }: NodeProps<TileFlowNodeType>): JSX.Element {
    const { node, workflow, motion, count, selected, menuOpen, countOf, templateNameOf } = data
    const motionStyle = motionProps(motion)

    return (
        <div className={cn(motionStyle.className)} style={motionStyle.style}>
            <Handle type="target" position={Position.Top} className="!opacity-0" isConnectable={false} />
            {node.kind === 'step' ? (
                <TileStepNode
                    action={node.action}
                    workflow={workflow}
                    count={count}
                    selected={selected}
                    menuOpen={menuOpen}
                />
            ) : (
                <TileStackNode
                    group={node.group}
                    workflow={workflow}
                    countOf={countOf}
                    templateNameOf={templateNameOf}
                />
            )}
            <Handle type="source" position={Position.Bottom} className="!opacity-0" isConnectable={false} />
        </div>
    )
}
