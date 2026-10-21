import { NodeProps } from '@xyflow/react'

import { cn } from 'lib/utils/css-classes'

import { motionProps } from './motionProps'
import { pathColor, tint } from './tileCanvasModel'
import type { PathFrameNodeType } from './tileCanvasNodes'

export function PathFrame({ data, width, height }: NodeProps<PathFrameNodeType>): JSX.Element {
    const color = pathColor(data.group.entryEdge)
    const motionStyle = motionProps(data.motion)
    return (
        <div className={cn('relative', motionStyle.className)} style={{ width, height, ...motionStyle.style }}>
            <div className="absolute inset-0 rounded-2xl" style={{ backgroundColor: tint(color, 6) }} />
            <div className="absolute bottom-3 left-0 top-3 w-[3px] rounded-full" style={{ backgroundColor: color }} />
        </div>
    )
}
