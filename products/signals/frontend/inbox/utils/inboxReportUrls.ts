import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { InboxTabKey } from '../types'

/**
 * A report's detail URL, with an optional `back` path for surfaces outside the inbox that embed
 * report cards (the detail header reads it to label its back button). Under the redesign the
 * Reports list is one column of sections, so `tab` stays `reports` and back always lands where the
 * card was; the legacy layout addresses the report through the tab that listed it.
 */
export function inboxReportDetailUrl(reportId: string, backUrl?: string, tab: InboxTabKey = 'reports'): string {
    return backUrl
        ? combineUrl(urls.inboxReport(tab, reportId), { back: backUrl }).url
        : urls.inboxReport(tab, reportId)
}

/**
 * Where an `/inbox/<tab>` segment from the legacy layout lands under the redesign, or null for a
 * segment the current layout serves itself. Slack notifications, bookmarks, and links from other
 * products carry whichever segments were live when they were written, so the redesign redirects
 * the segments it replaced: the three old report lists (`pulls`, `archived`, `not-actionable`) are
 * sections of one list, and Runs is a panel.
 *
 * Every redirect here points one way, from a segment the redesign no longer serves to the surface
 * that replaced it. A pair of segments that redirect to each other cannot be resolved this way,
 * because the flag is read from local storage before the server answers it: see
 * `resolveInboxTabAlias`.
 */
export function inboxTabRedirectPath(tab: string | undefined, redesign: boolean): string | null {
    if (!redesign) {
        return null
    }
    switch (tab) {
        case 'pulls':
        case 'archived':
        case 'not-actionable':
            return urls.inbox('reports')
        case 'runs':
            return urls.inboxRuns()
        default:
            return null
    }
}

/**
 * The tab an `/inbox/<tab>` segment names in the active layout. The settings surface has one
 * segment per layout — `config` with the flag off, `settings` under the redesign — and both are
 * live in bookmarks and Slack links.
 *
 * The pair is resolved to a tab, and the URL is left alone. A redirect cannot resolve it: each
 * segment would redirect to the other, and the flag they are read against changes at least once
 * per load, because the persisted value answers before the server does. That bounced the user
 * between `/inbox/config` and `/inbox/settings`.
 */
export function resolveInboxTabAlias(tab: string | undefined, redesign: boolean): string | undefined {
    if (redesign && tab === 'config') {
        return 'settings'
    }
    if (!redesign && tab === 'settings') {
        return 'config'
    }
    return tab
}
