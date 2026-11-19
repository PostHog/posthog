/**
 * The feed's horizontal pages, left to right: Moment, Full recording, then the Sessions page. A swipe moves one page
 * at a time. These run as worklets in the gestures, and in plain JS in tests.
 */

/** How far a drag has to travel, in points, or how fast it has to end, in points a second, to change the page. */
const SWIPE_DISTANCE = 64
const SWIPE_VELOCITY = 600
/** The tab highlight reaches the other tab after this share of the screen width. */
const TAB_TRAVEL = 0.6

export const SESSIONS_SLIDE_MS = 260

export type SwipeOutcome = 'stay' | 'moment' | 'session' | 'sessions'

function clamp(value: number): number {
    'worklet'
    return Math.min(1, Math.max(0, value))
}

/**
 * Where the tab highlight (0 Moment, 1 Full recording) and the Sessions page (0 hidden, 1 shown) sit while a finger
 * drags sideways on the video. `tabBase` is the tab the drag started on.
 */
export function swipeDrag(tabBase: number, translationX: number, width: number): { tab: number; sessions: number } {
    'worklet'
    if (tabBase === 1 && translationX < 0) {
        return { tab: 1, sessions: clamp(-translationX / Math.max(1, width)) }
    }
    return { tab: clamp(tabBase - translationX / Math.max(1, width * TAB_TRAVEL)), sessions: 0 }
}

/** The page a sideways swipe on the video lands on. A short, slow swipe stays. */
export function swipeOutcome(tabBase: number, translationX: number, velocityX: number): SwipeOutcome {
    'worklet'
    const far = Math.abs(translationX) > SWIPE_DISTANCE || Math.abs(velocityX) > SWIPE_VELOCITY
    if (!far) {
        return 'stay'
    }
    if (translationX < 0) {
        return tabBase === 0 ? 'session' : 'sessions'
    }
    return tabBase === 1 ? 'moment' : 'stay'
}

/** How much of the Sessions page shows while a finger drags it to the right, back toward the video. */
export function sessionsDrag(translationX: number, width: number): number {
    'worklet'
    return clamp(1 - Math.max(0, translationX) / Math.max(1, width))
}

/** True when a swipe to the right on the Sessions page goes back to the video. */
export function sessionsCloses(translationX: number, velocityX: number): boolean {
    'worklet'
    return translationX > SWIPE_DISTANCE || velocityX > SWIPE_VELOCITY
}
