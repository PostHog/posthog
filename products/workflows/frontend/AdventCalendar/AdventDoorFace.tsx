import { IconLock } from '@posthog/icons'

import { ADVENT_DOOR_SIZE, AdventDoor, adventDoorColor } from './adventGraph'
import { AdventRewardArt } from './AdventRewardArt'

export interface AdventDoorFaceProps {
    door: AdventDoor
    size: number
    zoom: number
    onClick: () => void
}

export function AdventDoorFace({ door, size, zoom, onClick }: AdventDoorFaceProps): JSX.Element {
    const color = adventDoorColor(door)
    return (
        <button
            type="button"
            className="AdventCard__face"
            style={{ width: size, height: size }}
            aria-label={`Door ${door.day}`}
            onClick={onClick}
        >
            {door.status === 'open' && door.reward ? (
                <AdventRewardArt reward={door.reward} className="size-full" />
            ) : (
                <span
                    className="AdventCard__door"
                    style={{
                        width: ADVENT_DOOR_SIZE,
                        height: ADVENT_DOOR_SIZE,
                        transform: `scale(${zoom})`,
                        borderColor: color,
                        color: door.status === 'ready' ? color : 'var(--color-text-tertiary)',
                    }}
                >
                    {door.day}
                    {door.status === 'locked' && <IconLock className="absolute right-1 top-1 text-sm" />}
                </span>
            )}
        </button>
    )
}
