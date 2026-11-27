import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

// The API returns an absolute link. Routing its path keeps the click inside the app.
export function appPath(url: string): string {
    const parsed = new URL(url, window.location.origin)
    return `${parsed.pathname}${parsed.search}${parsed.hash}`
}

/** Opens the new alert form on the insight the link points to. Null when the link names no insight. */
export function newAlertPath(insightUrl: string): string | null {
    const shortId = new URL(insightUrl, window.location.origin).pathname.match(/\/insights\/([^/]+)\/?$/)?.[1]
    return shortId ? urls.insightAlert(shortId as InsightShortId, 'new') : null
}
