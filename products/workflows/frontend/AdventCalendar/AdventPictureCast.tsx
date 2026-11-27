import './AdventPictureCast.scss'

import { CSSProperties } from 'react'

import { cn } from 'lib/utils/css-classes'

import type { AdventPollShares } from './adventCalendarLogic'
import {
    ADVENT_PICTURE,
    AdventDoor,
    adventDoorCenter,
    adventDoorGround,
    AdventGraph,
    adventHogSize,
    adventPictureAt,
    AdventPoint,
    openDoors,
} from './adventGraph'
import { AdventRevealBurst } from './AdventRevealBurst'
import { AdventRewardArt } from './AdventRewardArt'
import type { AdventRevealPhase } from './useAdventReveal'

const { width: WIDTH, height: HEIGHT } = ADVENT_PICTURE

const REVEAL_SCALE = 0.8
const REVEAL_MARGIN = { x: 95, y: 110 }

function inside(point: AdventPoint): AdventPoint {
    return {
        x: Math.max(REVEAL_MARGIN.x, Math.min(WIDTH - REVEAL_MARGIN.x, point.x)),
        y: Math.max(REVEAL_MARGIN.y, Math.min(HEIGHT - REVEAL_MARGIN.y, point.y)),
    }
}

export interface AdventPictureReveal {
    door: AdventDoor
    phase: AdventRevealPhase
    zoom: number
}

export interface AdventPictureCastProps {
    graph: AdventGraph
    shares?: AdventPollShares
    reveal?: AdventPictureReveal | null
    onActivateDoor?: (doorId: string) => void
    onEnterDoor?: (doorId: string) => void
    onLeaveDoor?: () => void
}

export function AdventPictureCast({
    graph,
    shares,
    reveal,
    onActivateDoor,
    onEnterDoor,
    onLeaveDoor,
}: AdventPictureCastProps): JSX.Element {
    const onSelectHog = reveal ? undefined : onActivateDoor
    const hogs = openDoors(graph).flatMap((door) =>
        door.reward && door.id !== reveal?.door.id ? [{ door, reward: door.reward }] : []
    )

    return (
        <>
            {hogs.map(({ door, reward }) => {
                const ground = adventDoorGround(door)
                const size = { '--advent-hog-size': `${adventHogSize(door) / 12}cqw` } as CSSProperties
                const art = (
                    <>
                        <span className="AdventPicture__shadow" />
                        <AdventRewardArt reward={reward} className="relative size-full" isTitled />
                    </>
                )
                return (
                    <span
                        key={door.id}
                        className="AdventPicture__spot"
                        style={{ ...adventPictureAt(ground), zIndex: Math.round(ground.y) }}
                    >
                        {onActivateDoor ? (
                            <button
                                type="button"
                                data-attr={`advent-hog-${door.day}`}
                                aria-label={`Door ${door.day}, open: ${reward.name}`}
                                className={cn('AdventPicture__hog', onSelectHog && 'AdventPicture__hog--button')}
                                style={size}
                                disabled={!onSelectHog}
                                onClick={onSelectHog && (() => onSelectHog(door.id))}
                                onMouseEnter={onSelectHog && (() => onEnterDoor?.(door.id))}
                                onMouseLeave={onSelectHog && onLeaveDoor}
                            >
                                {art}
                            </button>
                        ) : (
                            <span data-attr={`advent-hog-${door.day}`} className="AdventPicture__hog" style={size}>
                                {art}
                            </span>
                        )}
                        {door.question && door.answer && (
                            <span className="AdventPicture__pick" data-attr="advent-door-pick">
                                <span className="AdventPicture__pick-topic">{door.question.topic}</span>
                                <span className="AdventPicture__pick-answer">{door.answer.label}</span>
                                {shares?.[door.day]?.[door.answer.id] !== undefined && (
                                    <span className="AdventPicture__pick-topic">
                                        {`${shares[door.day][door.answer.id]}% agree`}
                                    </span>
                                )}
                            </span>
                        )}
                    </span>
                )
            })}
            {reveal && (
                <span
                    className="AdventPicture__reveal"
                    style={
                        {
                            ...adventPictureAt(inside(adventDoorCenter(reveal.door))),
                            '--advent-reveal-scale': reveal.zoom * REVEAL_SCALE,
                        } as CSSProperties
                    }
                    data-attr="advent-reveal"
                    data-phase={reveal.phase}
                >
                    <AdventRevealBurst door={reveal.door} phase={reveal.phase} />
                </span>
            )}
        </>
    )
}
