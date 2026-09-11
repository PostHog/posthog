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
 * The `?back=` path a report was opened with, or null when it carries none. Only an internal path is
 * honored: the value reaches the URL from anywhere, so an absolute or protocol-relative one would
 * turn the back button (and the verdict actions that follow it) into an open redirect.
 */
export function inboxReportBackPath(searchParams: Record<string, any>): string | null {
    const raw = searchParams.back
    return typeof raw === 'string' && raw.startsWith('/') && !raw.startsWith('//') ? raw : null
}

/**
 * Where a report's back button and its verdict actions (dismiss, resolve, refund, restore) leave to:
 * the surface the report was opened from when it carries one, the current list tab otherwise. A
 * report opened from a scout page, the findings panel or triage has to come back to it — the reader
 * was working through that surface, not the list.
 */
export function inboxReportReturnPath(searchParams: Record<string, any>, activeTab: InboxTabKey): string {
    return inboxReportBackPath(searchParams) ?? urls.inbox(activeTab)
}

/**
 * Where an `/inbox/<tab>` segment from the other inbox layout lands, or null for a segment the
 * current layout serves itself. Slack notifications, bookmarks, and links from other products
 * carry whichever segments were live when they were written, and the flag can flip between
 * visits, so each layout owns a redirect for the other's segments.
 *
 * Under the redesign the three old report lists (`pulls`, `archived`, `not-actionable`) are
 * sections of one list, so they all resolve to it. With the flag off, the redesign's Settings
 * tab is the Configuration tab.
 */
export function inboxTabRedirectPath(tab: string | undefined, redesign: boolean): string | null {
    if (!redesign) {
        return tab === 'settings' ? urls.inbox('config') : null
    }
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
