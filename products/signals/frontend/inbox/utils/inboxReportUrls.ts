import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

/**
 * A report's detail URL, with an optional `back` path for surfaces outside the inbox that embed
 * report cards (the detail header reads it to label its back button). The Reports list is one
 * column of sections, so back always lands where the card was.
 */
export function inboxReportDetailUrl(reportId: string, backUrl?: string): string {
    return backUrl
        ? combineUrl(urls.inboxReport('reports', reportId), { back: backUrl }).url
        : urls.inboxReport('reports', reportId)
}

/**
 * Where an `/inbox/<tab>` segment from the old inbox layout lands, or null for a segment the inbox
 * serves itself. Slack notifications, bookmarks, and links from other products carry whichever
 * segments were live when they were written.
 *
 * The three old report lists (`pulls`, `archived`, `not-actionable`) are sections of one list, so
 * they all resolve to it.
 */
export function inboxTabRedirectPath(tab: string | undefined): string | null {
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
