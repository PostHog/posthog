import { useEffect, useRef, useState } from 'react'

import { cn } from 'lib/utils/css-classes'

import type { HogFlow } from '../../types'
import { MiniFlow } from './MiniFlow'
import { TILE_SIZE } from './tileCanvasLayout'
import type { PathGroup } from './tileCanvasModel'
import { useKeepInView } from './useKeepInView'

/** A closed peek renders no mini flow, so a stack of hidden steps costs nothing until someone looks inside. */
function useHasOpened(open: boolean): boolean {
    const [hasOpened, setHasOpened] = useState(open)
    useEffect(() => {
        if (open) {
            setHasOpened(true)
        }
    }, [open])
    return hasOpened || open
}

export function StackPeek({
    group,
    workflow,
    color,
    open,
    countOf,
}: {
    group: PathGroup
    workflow: HogFlow
    color: string
    open: boolean
    countOf: (actionId: string) => number | undefined
}): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)
    const shift = useKeepInView(ref, open)
    const hasOpened = useHasOpened(open)
    return (
        <div
            ref={ref}
            className={cn(
                'absolute z-10 rounded-2xl border bg-surface-primary p-3 shadow-xl transition-opacity duration-150 motion-reduce:transition-none',
                open ? 'visible opacity-100' : 'invisible opacity-0'
            )}
            style={{
                left: TILE_SIZE + 12,
                top: -14,
                transform: `translate(${shift.x}px, ${shift.y}px)`,
                borderColor: color,
            }}
        >
            <div className="mb-3 flex items-center gap-1.5 whitespace-nowrap text-[11px]">
                <span className="size-2 rounded-full" style={{ backgroundColor: color }} />
                <span className="font-semibold" style={{ color }}>
                    {group.label}
                </span>
                <span className="text-secondary">{group.memberIds.length} steps, click to open</span>
            </div>
            <div className="px-1 pt-1">
                {hasOpened && (
                    <MiniFlow workflow={workflow} memberIds={group.memberIds} countOf={countOf} open={open} />
                )}
            </div>
        </div>
    )
}
