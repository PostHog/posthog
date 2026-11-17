import { IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { TileBadge } from './TileBadge'
import { TILE_SIZE } from './tileCanvasLayout'
import type { TileShape, TileStep } from './useTileStep'

const CORNER = 12
const NEEDS_ATTENTION = 'This step needs attention. Open it to see what is missing.'

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
                <Tooltip title={NEEDS_ATTENTION}>
                    <span
                        className="absolute -left-3 -top-3 z-[2] flex size-6 items-center justify-center rounded-full border-2 border-primary bg-warning text-black shadow-sm"
                        role="img"
                        aria-label={NEEDS_ATTENTION}
                    >
                        <IconWarning className="size-4" />
                    </span>
                </Tooltip>
            )}
        </div>
    )
}
