import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

/** Every Replay vision scene hangs off this crumb, so it lives in one place rather than six. */
export const VISION_ROOT_BREADCRUMB: Breadcrumb = {
    key: 'replay-vision',
    name: 'Replay vision',
    path: urls.replayVision(),
    iconType: 'replay_vision',
}

/**
 * The home view an observation was opened from, carried in its URL's `from` param. The watch feed
 * lives on the home scene, not the scanner that owns a row, so back needs this to return to the feed
 * rather than the scanner. Absent for observations opened from a scanner's own list.
 */
export const OBSERVATION_ORIGIN_PARAM = 'from'
export const WATCH_FEED_ORIGIN = 'watch'
export const RECORDING_ORIGIN = 'recording'
export const POSTHOG_AI_ORIGIN = 'ai'
/** The in-app path a PostHog AI thread was open on, which can be any scene when it is in the side panel. */
export const OBSERVATION_RETURN_PATH_PARAM = 'return_to'

const OBSERVATION_ORIGINS: readonly string[] = [WATCH_FEED_ORIGIN, RECORDING_ORIGIN, POSTHOG_AI_ORIGIN]

export function isObservationOrigin(value: unknown): value is string {
    return typeof value === 'string' && OBSERVATION_ORIGINS.includes(value)
}

/** Accepts only a same-origin path, so a crafted link can't point the back button at another site. */
export function safeReturnPath(value: unknown): string | null {
    return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : null
}

export function observationFromRecordingUrl(observationId: string): string {
    return combineUrl(urls.replayVisionObservation(observationId), { [OBSERVATION_ORIGIN_PARAM]: RECORDING_ORIGIN }).url
}

export function observationFromPosthogAiUrl(observationId: string, returnPath: string): string {
    return combineUrl(urls.replayVisionObservation(observationId), {
        [OBSERVATION_ORIGIN_PARAM]: POSTHOG_AI_ORIGIN,
        [OBSERVATION_RETURN_PATH_PARAM]: returnPath,
    }).url
}

export function posthogAiBreadcrumb(returnPath: string | null): Breadcrumb {
    return {
        key: 'replay-vision-posthog-ai',
        name: 'PostHog AI',
        path: returnPath ?? urls.ai(),
    }
}

/** The crumb the back button returns to for an observation opened from the "What to watch" feed. */
export function watchFeedBreadcrumb(): Breadcrumb {
    return {
        key: 'replay-vision-watch',
        name: 'What to watch',
        path: combineUrl(urls.replayVision(), { tab: WATCH_FEED_ORIGIN }).url,
    }
}

/** A crumb pointing at a saved scanner's page, optionally deep-linked to one of its tabs and its state. */
export function scannerBreadcrumb(
    scannerId: string,
    name?: string | null,
    searchParams?: Record<string, string | number>
): Breadcrumb {
    const path = urls.replayVision(scannerId)
    return {
        key: `scanner-${scannerId}`,
        name: name || 'Scanner',
        // combineUrl with no params returns the path unchanged, so the empty case needs no guard.
        path: combineUrl(path, searchParams ?? {}).url,
    }
}
