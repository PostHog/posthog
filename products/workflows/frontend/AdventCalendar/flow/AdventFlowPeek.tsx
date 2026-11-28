import { CSSProperties } from 'react'

import { cn } from 'lib/utils/css-classes'

import { AdventDoor, adventDayColor } from '../adventGraph'
import { AdventRewardArt } from '../AdventRewardArt'
import { ADVENT_FLOW_DOOR } from './adventFlowLayout'

interface Pose {
    height: number
    sink: number
    shift: number
}

const POSES: Record<string, Partial<Pose>> = {
    safari: { height: 100, sink: 0.12, shift: 18 },
    scientist: { height: 93, sink: 0.4, shift: 15 },
}

const DEFAULT_POSE: Pose = { height: 87, sink: 0.3, shift: 13 }
const PORTRAIT_POSE: Pose = { height: 47, sink: 0, shift: 8 }
const PORTRAIT_LIFT = 7
const WIDEST_HOGGY = ADVENT_FLOW_DOOR.width * 1.8

function poseOf(door: AdventDoor): Pose {
    const reward = door.reward
    if (reward?.isPortrait) {
        return PORTRAIT_POSE
    }
    const pose = { ...DEFAULT_POSE, ...(reward ? POSES[reward.id] : null) }
    const aspectRatio = reward?.image.aspectRatio ?? 1
    return { ...pose, height: Math.min(pose.height, WIDEST_HOGGY / aspectRatio) }
}

function hoggyStyle(door: AdventDoor): CSSProperties {
    const pose = poseOf(door)
    const isPortrait = !!door.reward?.isPortrait
    const width = pose.height * (isPortrait ? 1 : (door.reward?.image.aspectRatio ?? 1))
    return {
        left: (ADVENT_FLOW_DOOR.width - width) / 2 + pose.shift,
        top: ADVENT_FLOW_DOOR.height - pose.height * (1 - pose.sink) - (isPortrait ? PORTRAIT_LIFT : 0),
        width,
        height: pose.height,
    }
}

export interface AdventFlowPeekProps {
    door: AdventDoor
    isOpening: boolean
}

export function AdventFlowPeek({ door, isOpening }: AdventFlowPeekProps): JSX.Element {
    const color = adventDayColor(door.day)
    return (
        <span className={cn('AdventFlowPeek', isOpening && 'AdventFlowPeek--opening')}>
            <span className="AdventFlowPeek__stitch" />
            <span className="AdventFlowPeek__window">
                {door.reward && (
                    <span className="AdventFlowPeek__hoggy" style={hoggyStyle(door)}>
                        <AdventRewardArt reward={door.reward} className="size-full" />
                    </span>
                )}
                <span className="AdventFlowPeek__shade" />
            </span>
            <span className="AdventFlowPeek__frame" />
            <span className="AdventFlowPeek__hinge">
                <span className="AdventFlowPeek__leaf">
                    <span className="AdventFlowPeek__face" style={{ borderColor: color, color }}>
                        {door.day}
                    </span>
                    <span className="AdventFlowPeek__face AdventFlowPeek__face--back" style={{ borderColor: color }} />
                </span>
            </span>
        </span>
    )
}
