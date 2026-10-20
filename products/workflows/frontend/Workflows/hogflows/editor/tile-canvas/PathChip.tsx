import { NodeProps } from '@xyflow/react'
import { useActions } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

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
            <div
                className="nodrag flex w-max items-center gap-1.5 whitespace-nowrap rounded-full border bg-surface-primary pr-2.5 shadow-sm"
                style={{ borderColor: color }}
            >
                <LemonButton
                    size="xsmall"
                    icon={<IconChevronDown />}
                    tooltip="Collapse this path"
                    data-attr="workflow-tile-collapse-path"
                    onClick={(event) => {
                        event.stopPropagation()
                        collapsePath(data.group.id)
                    }}
                />
                <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
                <span className="text-[13px] font-semibold" style={{ color }}>
                    {data.group.label}
                </span>
            </div>
        </div>
    )
}
