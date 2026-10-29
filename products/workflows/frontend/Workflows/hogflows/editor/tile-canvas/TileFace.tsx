import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { TileBadge } from './TileBadge'
import { TILE_SIZE } from './tileCanvasLayout'
import type { TileShape, TileStep } from './tileStep'

const CORNER = 12

function tileRadius(shape: TileShape): string {
    const round = `${TILE_SIZE / 2}px`
    return shape === 'start'
        ? `${round} ${round} ${CORNER}px ${CORNER}px`
        : shape === 'end'
          ? `${CORNER}px ${CORNER}px ${round} ${round}`
          : `${CORNER}px`
}

export function TileFace({
    tile,
    count,
    marker,
}: {
    tile: TileStep
    count: number | undefined
    marker?: React.ReactNode
}): JSX.Element {
    return (
        <div className="relative" data-tile-anchor>
            <div
                className="flex items-center justify-center border-2 bg-surface-primary text-[30px] shadow-sm"
                style={{
                    width: TILE_SIZE,
                    height: TILE_SIZE,
                    borderRadius: tileRadius(tile.shape),
                    borderColor: tile.color,
                    color: tile.color,
                }}
            >
                {tile.icon}
            </div>
            {count !== undefined && <TileBadge placement="count">{humanFriendlyLargeNumber(count)}</TileBadge>}
            {tile.badge && (
                <TileBadge placement="setting" color={tile.color}>
                    {tile.badge}
                </TileBadge>
            )}
            {marker}
        </div>
    )
}
