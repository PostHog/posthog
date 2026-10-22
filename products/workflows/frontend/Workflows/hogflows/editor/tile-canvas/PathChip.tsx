import { NodeProps } from '@xyflow/react'
import { useActions } from 'kea'

import { IconCollapse } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { motionProps } from './motionProps'
import { shortLabel } from './tileCanvasLayout'
import { tileCanvasLogic } from './tileCanvasLogic'
import { pathColor } from './tileCanvasModel'
import type { PathChipNodeType } from './tileCanvasNodes'

export function PathChip({ data }: NodeProps<PathChipNodeType>): JSX.Element {
    const { collapsePath } = useActions(tileCanvasLogic)
    const color = pathColor(data.group.entryEdge)
    const motionStyle = motionProps(data.motion)
    return (
        <div className={cn('-translate-y-1/2', motionStyle.className)} style={motionStyle.style}>
            <button
                type="button"
                className="nodrag group flex w-max cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full border bg-surface-primary py-1 pl-2.5 pr-1 shadow-sm"
                style={{ borderColor: color }}
                title={data.group.label === shortLabel(data.group.label) ? undefined : data.group.label}
                data-attr="workflow-tile-collapse-path"
                onClick={(event) => {
                    event.stopPropagation()
                    collapsePath(data.group.id)
                }}
            >
                <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
                <span className="text-[13px] font-semibold" style={{ color }}>
                    {shortLabel(data.group.label)}
                </span>
                <span className="flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-medium text-secondary group-hover:bg-fill-button-tertiary-hover group-hover:text-primary">
                    <IconCollapse className="size-3" />
                    Collapse
                </span>
            </button>
        </div>
    )
}
