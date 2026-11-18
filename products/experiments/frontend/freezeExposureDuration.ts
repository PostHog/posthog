// Fitted to the experiment_freeze_exposure_timing logs of US production as of October 2026: under one
// second of fixed cost, plus 0.32 to 0.36 ms for each exposed user. Both values are rounded up, so the
// estimate is a little long rather than short.
const FIXED_SECONDS = 1
const SECONDS_PER_EXPOSED_USER = 0.0004

export function estimateFreezeExposureSeconds(exposedUsers: number): number {
    return FIXED_SECONDS + exposedUsers * SECONDS_PER_EXPOSED_USER
}

/** Rounds more coarsely as the duration grows, so the text is never more precise than the estimate. */
export function formatFreezeExposureDuration(seconds: number): string {
    if (seconds < 5) {
        return 'a few seconds'
    }
    const step = seconds < 10 ? 1 : seconds < 60 ? 5 : 10
    const rounded = Math.round(seconds / step) * step
    if (rounded < 60) {
        return `about ${rounded} seconds`
    }
    const minutes = Math.floor(rounded / 60)
    const remainder = rounded % 60
    const minutesText = `${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`
    return remainder === 0 ? `about ${minutesText}` : `about ${minutesText} ${remainder} seconds`
}
