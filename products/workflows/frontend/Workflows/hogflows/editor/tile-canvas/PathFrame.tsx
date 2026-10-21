import { NodeProps } from '@xyflow/react'

import { cn } from 'lib/utils/css-classes'

import { motionProps } from './motionProps'
import type { PathFrameNodeType } from './tileCanvasNodes'

export function PathFrame({ data, width, height }: NodeProps<PathFrameNodeType>): JSX.Element {
    const motionStyle = motionProps(data.motion)
    // A fill or rail stacks on a deeply nested workflow, so the label and the path trail name an open path instead.
    return <div className={cn('relative', motionStyle.className)} style={{ width, height, ...motionStyle.style }} />
}
