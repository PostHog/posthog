/** How far a hold must pull down to lock or unlock: far enough that a resting finger does not drift into it. */
export const HOLD_PULL = 72

export interface HoldLock {
    rate: number
}

export interface Hold {
    /** The hold started while a lock was on, so releasing past the pull unlocks instead of locking. */
    locked: boolean
    rate: number
    armed: boolean
}

export type HoldResult = 'locked' | 'unlocked' | null

/** A hold always speeds up: 2x, or 4x when the set speed is 2x or 3x. At 4x or more a hold does nothing. */
export function holdRateFor(speed: number): number | null {
    if (speed >= 4) {
        return null
    }
    return speed >= 2 ? 4 : 2
}

export function startHold(speed: number, lock: HoldLock | null): Hold | null {
    if (lock) {
        return { locked: true, rate: lock.rate, armed: false }
    }
    const rate = holdRateFor(speed)
    return rate === null ? null : { locked: false, rate, armed: false }
}

/** Moving back above the threshold disarms, so only a release past it locks or unlocks. */
export function pullHold(hold: Hold, pull: number): Hold {
    const armed = pull >= HOLD_PULL
    return armed === hold.armed ? hold : { ...hold, armed }
}

export function releaseHold(
    hold: Hold,
    lock: HoldLock | null,
    cancelled: boolean
): { lock: HoldLock | null; result: HoldResult } {
    if (cancelled || !hold.armed) {
        return { lock, result: null }
    }
    return hold.locked ? { lock: null, result: 'unlocked' } : { lock: { rate: hold.rate }, result: 'locked' }
}

export function playbackRate(speed: number, hold: Hold | null, lock: HoldLock | null): number {
    return hold?.rate ?? lock?.rate ?? speed
}
