import { NodeProps } from '@xyflow/react'

import { cn } from 'lib/utils/css-classes'

import { motionProps } from './motionProps'
import { tint } from './tileCanvasModel'
import type { PathFrameNodeType } from './tileCanvasNodes'

export function PathFrame({ data, width, height }: NodeProps<PathFrameNodeType>): JSX.Element {
    const motionStyle = motionProps(data.motion)
    // A path color would stack into one solid hue on a nested workflow, so every open path gets the same light gray.
    return (
        <div className={cn('relative', motionStyle.className)} style={{ width, height, ...motionStyle.style }}>
            <div
                className="absolute inset-0 rounded-2xl"
                style={{ backgroundColor: tint('var(--color-text-secondary)', 6) }}
            />
        </div>
    )
}
