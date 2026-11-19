import { combineUrl } from 'kea-router'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { getRelativeNextPath } from 'lib/utils/url'
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
 * The home view an observation was opened from, carried in its URL's `from` param. The highlight feed
 * lives on the home scene, not the scanner that owns a row, so back needs this to return to the feed
 * rather than the scanner. Absent for observations opened from a scanner's own list.
 */
export const OBSERVATION_ORIGIN_PARAM = 'from'
/** The home tab that shows the highlight feed, also the `from` value of an observation opened from it. */
export const HIGHLIGHTS_TAB = 'highlights'
export const HIGHLIGHT_FEED_ORIGIN = HIGHLIGHTS_TAB
export const RECORDING_ORIGIN = 'recording'
export const POSTHOG_AI_ORIGIN = 'ai'
/** The in-app page the reader left, such as a playlist or the scene a PostHog AI side panel was open over. */
export const OBSERVATION_RETURN_PATH_PARAM = 'return_to'

export type ReturnOrigin = typeof RECORDING_ORIGIN | typeof POSTHOG_AI_ORIGIN

const OBSERVATION_ORIGINS: readonly string[] = [HIGHLIGHT_FEED_ORIGIN, RECORDING_ORIGIN, POSTHOG_AI_ORIGIN]

export function isObservationOrigin(value: unknown): value is string {
    return typeof value === 'string' && OBSERVATION_ORIGINS.includes(value)
}

/** Accepts only a same-origin path, so a crafted link can't point the back button at another site. */
export function safeReturnPath(value: unknown): string | null {
    return typeof value === 'string' ? getRelativeNextPath(value, window.location) : null
}

/** The current in-app path, without the project prefix, for an observation link's `return_to`. */
export function currentReturnPath(location: { pathname: string; search: string; hash: string }): string {
    // The hash matters: the player modal keeps the open recording there.
    return removeProjectIdIfPresent(location.pathname) + location.search + location.hash
}

export function observationFromOriginUrl(observationId: string, origin: ReturnOrigin, returnPath?: string): string {
    return combineUrl(urls.replayVisionObservation(observationId), {
        [OBSERVATION_ORIGIN_PARAM]: origin,
        ...(returnPath ? { [OBSERVATION_RETURN_PATH_PARAM]: returnPath } : {}),
    }).url
}

/** The crumb the back button returns to for an observation opened from the Highlights feed. */
export function highlightFeedBreadcrumb(): Breadcrumb {
    return {
        key: 'replay-vision-watch',
        name: 'Highlights',
        path: combineUrl(urls.replayVision(), { tab: HIGHLIGHTS_TAB }).url,
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
