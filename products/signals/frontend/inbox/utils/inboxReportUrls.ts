import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
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
 * Report detail URLs that return to the page the reader is on, for report links on inbox surfaces
 * other than the Reports list (a scout page with its pane and finding, findings, runs, scratchpad).
 */
export function useInboxReportDetailUrl(): (reportId: string) => string {
    const { location } = useValues(router)
    const backUrl = removeProjectIdIfPresent(location.pathname) + location.search
    return (reportId) => inboxReportDetailUrl(reportId, backUrl)
}

/** The report header's back button label for a `?back=` path, named for where it goes. */
export function inboxReportBackLabel(backUrl: string): string {
    if (backUrl.startsWith(urls.inboxTriage())) {
        return 'Triage'
    }
    const path = backUrl.split(/[?#]/)[0]
    switch (path) {
        case urls.inbox('monitoring'):
            return 'Monitoring'
        case urls.inbox('scouts'):
            return 'Scouts'
        case urls.inboxFindings():
            return 'Findings'
        case urls.inboxRuns():
            return 'Runs'
        case urls.inboxScratchpad():
            return 'Scratchpad'
    }
    return path.startsWith(`${urls.inbox('scouts')}/`) ? 'Scout' : 'Back'
}

/**
 * Where an `/inbox/<tab>` segment from the old inbox layout lands, or null for a segment the inbox
 * serves itself. Slack notifications, bookmarks, and links from other products carry whichever
 * segments were live when they were written.
 *
 * The three old report lists (`pulls`, `archived`, `not-actionable`) are sections of one list, so
 * they all resolve to it.
 */
export function inboxTabRedirectPath(
    tab: string | undefined,
    searchParams: Record<string, unknown> = {}
): string | null {
    // OAuth callbacks may still target the page where a source connection was started.
    if (searchParams.setup === 'signal-sources' && (tab === undefined || tab === 'config' || tab === 'settings')) {
        return urls.inbox('sources')
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
