import { CSSProperties } from 'react'

import { IconLock } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { ADVENT_LAST_DAY } from './adventContent'
import { ADVENT_DOOR_SIZE, AdventDoor, adventDoorColor } from './adventGraph'
import { AdventRewardArt } from './AdventRewardArt'

export interface AdventDoorFaceProps {
    door: AdventDoor
    size: number
    zoom: number
    style?: CSSProperties
    onClick: () => void
}

export function AdventDoorFace({ door, size, zoom, style, onClick }: AdventDoorFaceProps): JSX.Element {
    const color = adventDoorColor(door)
    const isExit = door.day === ADVENT_LAST_DAY
    return (
        <button
            type="button"
            className="AdventCard__face"
            style={{ ...style, width: size, height: size }}
            aria-label={`Door ${door.day}`}
            onClick={onClick}
        >
            {door.status === 'open' && door.reward ? (
                <AdventRewardArt reward={door.reward} className="size-full" />
            ) : (
                <span
                    className={cn('AdventCard__door', isExit && 'AdventDoor--exit')}
                    style={{
                        width: ADVENT_DOOR_SIZE,
                        height: ADVENT_DOOR_SIZE,
                        transform: `scale(${zoom})`,
                        borderColor: color,
                        color: door.status === 'ready' ? color : 'var(--color-text-tertiary)',
                    }}
                >
                    {door.day}
                    {door.status === 'locked' && (
                        <IconLock className={cn('absolute top-1 text-sm', isExit ? 'left-1' : 'right-1')} />
                    )}
                </span>
            )}
        </button>
    )
}
