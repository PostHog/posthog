import type { HogFlow, HogFlowAction } from '../../types'
import { MiniTile } from './MiniTile'
import type { MiniFlowLayout } from './tileCanvasModel'

export function MiniFlowStep({
    node,
    action,
    workflow,
    count,
    open,
    dimmed,
    highlighted,
    onEnter,
    onLeave,
}: {
    node: MiniFlowLayout['nodes'][number]
    action: HogFlowAction
    workflow: HogFlow
    count: number | undefined
    open: boolean
    dimmed: boolean
    highlighted: boolean
    onEnter: () => void
    onLeave: () => void
}): JSX.Element {
    return (
        <div
            className="absolute transition-[opacity,transform] duration-200 motion-reduce:transition-none"
            style={{
                left: node.x,
                top: node.y,
                opacity: open ? 1 : 0,
                transform: open ? 'none' : 'translateX(-10px) scale(0.85)',
                transitionDelay: `${node.layer * 40}ms`,
            }}
            onMouseEnter={onEnter}
            onMouseLeave={onLeave}
        >
            <MiniTile action={action} workflow={workflow} count={count} dimmed={dimmed} highlighted={highlighted} />
        </div>
    )
}
