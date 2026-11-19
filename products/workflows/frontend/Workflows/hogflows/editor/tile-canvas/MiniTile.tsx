import { cn } from 'lib/utils/css-classes'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { HogFlow, HogFlowAction } from '../../types'
import { TileBadge } from './TileBadge'
import { useTileStep } from './useTileStep'

export const MINI_TILE_SIZE = 32

export function MiniTile({
    action,
    workflow,
    count,
    dimmed,
    highlighted,
}: {
    action: HogFlowAction
    workflow: HogFlow
    count: number | undefined
    dimmed: boolean
    highlighted: boolean
}): JSX.Element {
    const tile = useTileStep(action, workflow)
    return (
        <div className={cn('relative transition-opacity duration-150', dimmed && 'opacity-35')}>
            <div
                className={cn(
                    'flex items-center justify-center rounded-lg border-2 bg-surface-primary text-[15px] transition-transform duration-150 motion-reduce:transition-none',
                    highlighted && 'scale-110 shadow-md'
                )}
                style={{ width: MINI_TILE_SIZE, height: MINI_TILE_SIZE, borderColor: tile.color, color: tile.color }}
            >
                {tile.icon}
            </div>
            {tile.badge && (
                <TileBadge placement="setting" size="mini" color={tile.color}>
                    {tile.badge}
                </TileBadge>
            )}
            {count !== undefined && (
                <TileBadge placement="count" size="mini">
                    {humanFriendlyLargeNumber(count)}
                </TileBadge>
            )}
        </div>
    )
}
