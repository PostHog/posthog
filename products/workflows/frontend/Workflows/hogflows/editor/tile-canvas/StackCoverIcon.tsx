import type { HogFlow, HogFlowAction } from '../../types'
import { tint } from './tileCanvasModel'
import { useTileStep } from './useTileStep'

export function StackCoverIcon({ action, workflow }: { action: HogFlowAction; workflow: HogFlow }): JSX.Element {
    const tile = useTileStep(action, workflow)
    return (
        <span
            className="flex size-[22px] items-center justify-center rounded text-[14px]"
            style={{ color: tile.color, backgroundColor: tint(tile.color, 10) }}
        >
            {tile.icon}
        </span>
    )
}
