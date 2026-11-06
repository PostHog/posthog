import { useEffect, useRef, useState } from 'react'

import { IconExpand } from '@posthog/icons'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { HogFlow } from '../../types'
import { StackCoverIcon } from './StackCoverIcon'
import { StackPeek } from './StackPeek'
import { pathSummary } from './stepFacts'
import { TileBadge } from './TileBadge'
import { TILE_SIZE } from './tileCanvasLayout'
import { pathActions, PathGroup, pathColor } from './tileCanvasModel'
import { isPointerMove } from './useHoverIntent'
import { useRaisedNode } from './useRaisedNode'

const PEEK_CLOSE_MS = 220
const STACK_OFFSETS = [8, 4]

export function TileStackNode({
    group,
    workflow,
    countOf,
    templateNameOf,
    interactive = true,
}: {
    group: PathGroup
    workflow: HogFlow
    countOf: (actionId: string) => number | undefined
    templateNameOf: (templateId: string) => string | undefined
    interactive?: boolean
}): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)
    const [peek, setPeek] = useState(false)
    const closeTimer = useRef<number>()
    useEffect(() => () => window.clearTimeout(closeTimer.current), [])
    useRaisedNode(ref, peek)

    const color = pathColor(group.entryEdge)
    const members = pathActions(workflow, group)
    const count = countOf(group.entryEdge.to)

    return (
        <div
            ref={ref}
            className="flex cursor-pointer items-start gap-3 text-primary"
            title={peek ? undefined : 'Open this path'}
            data-attr={interactive ? 'workflow-tile-stack' : undefined}
            onMouseMove={(event) => {
                if (interactive && isPointerMove(event)) {
                    window.clearTimeout(closeTimer.current)
                    setPeek(true)
                }
            }}
            onMouseLeave={() => {
                closeTimer.current = window.setTimeout(() => setPeek(false), PEEK_CLOSE_MS)
            }}
        >
            <div className="relative" data-tile-anchor style={{ width: TILE_SIZE, height: TILE_SIZE }}>
                {STACK_OFFSETS.map((offset) => (
                    <div
                        key={offset}
                        className="absolute inset-0 rounded-xl border-2 bg-surface-primary opacity-50"
                        style={{ transform: `translate(${offset}px, ${-offset}px)`, borderColor: color }}
                    />
                ))}
                <div
                    className="absolute inset-0 grid grid-cols-2 place-items-center gap-0.5 rounded-xl border-2 border-dashed bg-surface-primary p-1.5"
                    style={{ borderColor: color }}
                >
                    {members.slice(0, 4).map((action) => (
                        <StackCoverIcon key={action.id} action={action} workflow={workflow} />
                    ))}
                </div>
                {count !== undefined && <TileBadge placement="count">{humanFriendlyLargeNumber(count)}</TileBadge>}
                {interactive && (
                    <StackPeek group={group} workflow={workflow} color={color} open={peek} countOf={countOf} />
                )}
            </div>
            <div className="flex w-57.5 flex-col gap-0.5 pt-1 text-left">
                <div
                    className="line-clamp-2 break-words text-[13px] font-semibold leading-tight"
                    style={{ color }}
                    title={group.label}
                >
                    {group.label}
                </div>
                <div className="ph-no-capture break-words text-xs leading-snug">
                    {pathSummary(workflow, group, templateNameOf)}
                </div>
                <div className="flex items-center gap-1.5 text-[11px] text-secondary">
                    {members.length} steps
                    <span className="flex items-center gap-0.5 font-medium text-primary">
                        <IconExpand className="size-3" />
                        Open
                    </span>
                </div>
            </div>
        </div>
    )
}
