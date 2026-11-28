import { CSSProperties } from 'react'

import { IconLock } from '@posthog/icons'

import { ADVENT_LAST_DAY } from './adventContent'
import { ADVENT_DOOR_SIZE, AdventDoor, adventDoorColor } from './adventGraph'
import { AdventPresent } from './AdventPresent'
import { AdventRewardArt } from './AdventRewardArt'

export interface AdventDoorFaceProps {
    door: AdventDoor
    size: number
    zoom: number
    style?: CSSProperties
    tint?: string
    tabIndex?: number
    onClick: () => void
}

export function AdventDoorFace({ door, size, zoom, style, tint, tabIndex, onClick }: AdventDoorFaceProps): JSX.Element {
    const color = tint ?? adventDoorColor(door)
    return (
        <button
            type="button"
            className="AdventCard__face"
            style={{ ...style, width: size, height: size }}
            aria-label={`Door ${door.day}`}
            tabIndex={tabIndex}
            onClick={onClick}
        >
            {door.status === 'open' && door.reward ? (
                <AdventRewardArt reward={door.reward} className="size-full" />
            ) : door.day === ADVENT_LAST_DAY ? (
                <AdventPresent className="size-full" />
            ) : (
                <span
                    className="AdventCard__door"
                    style={{
                        width: ADVENT_DOOR_SIZE,
                        height: ADVENT_DOOR_SIZE,
                        transform: `scale(${zoom})`,
                        borderColor: color,
                        color: tint || door.status === 'ready' ? color : 'var(--color-text-tertiary)',
                    }}
                >
                    {door.day}
                    {door.status === 'locked' && !tint && <IconLock className="absolute right-1 top-1 text-sm" />}
                </span>
            )}
        </button>
    )
}
