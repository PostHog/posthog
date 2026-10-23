import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { TileBadge } from './TileBadge'
import { TILE_SIZE } from './tileCanvasLayout'
import type { TileShape, TileStep } from './useTileStep'

const CORNER = 12

function tileRadius(shape: TileShape): string {
    const round = `${TILE_SIZE / 2}px`
    return shape === 'start'
        ? `${round} ${round} ${CORNER}px ${CORNER}px`
        : shape === 'end'
          ? `${CORNER}px ${CORNER}px ${round} ${round}`
          : `${CORNER}px`
}

export function TileFace({ tile, count }: { tile: TileStep; count: number | undefined }): JSX.Element {
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
            {tile.invalid && (
                <Tooltip title="This step needs attention. Open it to see what is missing.">
                    <span className="absolute -left-1 -top-1 size-2.5 rounded-full border-2 border-primary bg-warning" />
                </Tooltip>
            )}
        </div>
    )
}
