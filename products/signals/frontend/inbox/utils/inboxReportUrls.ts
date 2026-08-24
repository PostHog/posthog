import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

/**
 * A report's detail URL, with an optional `back` path for surfaces outside the inbox that embed
 * report cards (the detail header reads it to label its back button). Inbox cards pass nothing:
 * the Reports list is one column of sections, so back always lands where the card was.
 */
export function inboxReportDetailUrl(reportId: string, backUrl?: string): string {
    return backUrl
        ? combineUrl(urls.inboxReport('reports', reportId), { back: backUrl }).url
        : urls.inboxReport('reports', reportId)
}

/**
 * Where a pre-redesign `/inbox/<tab>` segment lands now, or null for a segment that is still live.
 * Slack notifications, bookmarks, and links from other products still carry the old shapes. The
 * three report lists (`pulls`, `archived`, `not-actionable`) were folded into the Reports list's
 * sections, so they all resolve to it.
 */
export function legacyInboxTabPath(tab: string | undefined): string | null {
    switch (tab) {
        case 'pulls':
        case 'archived':
        case 'not-actionable':
            return urls.inbox('reports')
        case 'runs':
            return urls.inboxRuns()
        case 'config':
            return urls.inbox('settings')
        default:
            return null
    }
}
