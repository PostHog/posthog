import { NodeProps } from '@xyflow/react'
import { useActions } from 'kea'

import { IconCollapse } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { motionProps } from './motionProps'
import { tileCanvasLogic } from './tileCanvasLogic'
import { pathColor } from './tileCanvasModel'
import type { PathChipNodeType } from './tileCanvasNodes'

export function PathChip({ data }: NodeProps<PathChipNodeType>): JSX.Element {
    const { collapsePath } = useActions(tileCanvasLogic)
    const color = pathColor(data.group.entryEdge)
    const motionStyle = motionProps(data.motion)
    return (
        <div className={cn('-translate-y-1/2', motionStyle.className)} style={motionStyle.style}>
            <Tooltip title="Collapse this path">
                <button
                    type="button"
                    className="nodrag flex w-max cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full border bg-surface-primary py-1 pl-2 pr-2.5 shadow-sm hover:bg-surface-secondary"
                    style={{ borderColor: color }}
                    data-attr="workflow-tile-collapse-path"
                    onClick={(event) => {
                        event.stopPropagation()
                        collapsePath(data.group.id)
                    }}
                >
                    <IconCollapse className="size-3.5 shrink-0 text-secondary" />
                    <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
                    <span className="text-[13px] font-semibold" style={{ color }}>
                        {data.group.label}
                    </span>
                </button>
            </Tooltip>
        </div>
    )
}
