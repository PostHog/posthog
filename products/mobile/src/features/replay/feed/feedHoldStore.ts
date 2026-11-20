import { makeMutable } from 'react-native-reanimated'
import { create } from 'zustand'

import { type HapticKind, haptic } from '@/lib/haptics'

import { FEED_DEBUG } from './feedPerf'
import { type Hold, type HoldLock, type HoldResult, pullHold, releaseHold, startHold } from './holdLock'

interface FeedHoldState {
    hold: Hold | null
    /** The speed a pull locked. The set speed stays as it was, so an unlock plays at it again. */
    lock: HoldLock | null
}

export const useFeedHold = create<FeedHoldState>(() => ({ hold: null, lock: null }))

if (FEED_DEBUG) {
    ;(globalThis as { __replayFeedHold?: typeof useFeedHold }).__replayFeedHold = useFeedHold
}

/** The finger's pull below where the hold started, in points. The hold chip follows it on the UI thread. */
export const holdPull = makeMutable(0)

export type HoldHapticReason = 'start' | 'armed' | 'disarmed' | 'locked' | 'unlocked'

const HOLD_HAPTICS: Record<HoldHapticReason, HapticKind> = {
    start: 'heavy',
    armed: 'medium',
    disarmed: 'selection',
    locked: 'success',
    unlocked: 'success',
}

/** Each step of a hold has its own feel, so the finger knows when a release will lock or unlock. */
export function holdHaptic(reason: HoldHapticReason): void {
    haptic(HOLD_HAPTICS[reason])
    if (__DEV__) {
        const scope = globalThis as { __replayFeedHaptics?: unknown[] }
        scope.__replayFeedHaptics = [
            ...(scope.__replayFeedHaptics ?? []),
            { reason, kind: HOLD_HAPTICS[reason], at: Date.now() },
        ]
    }
}

export function beginHold(speed: number): Hold | null {
    const { hold: current, lock } = useFeedHold.getState()
    if (current) {
        return null
    }
    const hold = startHold(speed, lock)
    if (hold) {
        useFeedHold.setState({ hold })
    }
    return hold
}

export function armHold(pull: number): void {
    const { hold } = useFeedHold.getState()
    if (hold) {
        const next = pullHold(hold, pull)
        if (next !== hold) {
            useFeedHold.setState({ hold: next })
            holdHaptic(next.armed ? 'armed' : 'disarmed')
        }
    }
}

export function finishHold(cancelled: boolean): HoldResult {
    const { hold, lock } = useFeedHold.getState()
    if (!hold) {
        return null
    }
    const next = releaseHold(hold, lock, cancelled)
    useFeedHold.setState({ hold: null, lock: next.lock })
    holdPull.value = 0
    return next.result
}

export function unlockFeed(): boolean {
    if (!useFeedHold.getState().lock) {
        return false
    }
    useFeedHold.setState({ lock: null })
    return true
}

export function resetFeedHold(): void {
    useFeedHold.setState({ hold: null, lock: null })
    holdPull.value = 0
}
