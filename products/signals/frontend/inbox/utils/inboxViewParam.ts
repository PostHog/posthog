import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import {
    INBOX_DEFAULT_FLAT_LIST_TAB_KEY,
    INBOX_FLAT_LIST_TAB_KEYS,
    INBOX_STAFF_ONLY_FLAT_LIST_TAB_KEYS,
    InboxFlatListTabKey,
} from '../types'

/** Search param carrying the active Reports view. Pinned: it is part of shared and bookmarked URLs. */
export const INBOX_VIEW_SEARCH_PARAM = 'view'

export function isInboxFlatListTabKey(value: unknown): value is InboxFlatListTabKey {
    return typeof value === 'string' && (INBOX_FLAT_LIST_TAB_KEYS as readonly string[]).includes(value)
}

export function isStaffOnlyInboxView(view: InboxFlatListTabKey): boolean {
    return INBOX_STAFF_ONLY_FLAT_LIST_TAB_KEYS.includes(view)
}

/**
 * The Reports view a `?view=` value selects. Unknown values fall back to the landing view, and a
 * staff-only view falls back too once the user has resolved as non-staff. While the user is still
 * unresolved the value is kept, since bouncing then would misroute a staff member's own deep link.
 */
export function parseInboxViewParam(raw: unknown, user: { is_staff?: boolean } | null): InboxFlatListTabKey {
    if (!isInboxFlatListTabKey(raw)) {
        return INBOX_DEFAULT_FLAT_LIST_TAB_KEY
    }
    if (isStaffOnlyInboxView(raw) && user != null && !user.is_staff) {
        return INBOX_DEFAULT_FLAT_LIST_TAB_KEY
    }
    return raw
}

/** The given search params with the `view` param set, or dropped when it's the landing view. */
export function inboxViewSearchParams(
    searchParams: Record<string, any>,
    view: InboxFlatListTabKey
): Record<string, any> {
    const { [INBOX_VIEW_SEARCH_PARAM]: _view, ...rest } = searchParams
    return view === INBOX_DEFAULT_FLAT_LIST_TAB_KEY ? rest : { ...rest, [INBOX_VIEW_SEARCH_PARAM]: view }
}

/**
 * A report's detail URL, carrying the view it was opened from so the back button returns there, and
 * an optional `back` path for surfaces outside the inbox that embed report cards.
 */
export function inboxReportDetailUrl(reportId: string, view: InboxFlatListTabKey, backUrl?: string): string {
    const params = inboxViewSearchParams(backUrl ? { back: backUrl } : {}, view)
    return Object.keys(params).length > 0
        ? combineUrl(urls.inboxReport('reports', reportId), params).url
        : urls.inboxReport('reports', reportId)
}

/**
 * The Reports view a pre-redesign tab segment maps onto. Slack notifications, bookmarks, and links
 * from other products still carry the old `/inbox/pulls` and `/inbox/archived` shapes. Null for
 * segments that were never a report list.
 */
export function legacyInboxTabView(tab: string | undefined): InboxFlatListTabKey | null {
    switch (tab) {
        case 'pulls':
            return 'monitoring'
        case 'archived':
            return 'resolved'
        case 'not-actionable':
            return 'not-actionable'
        default:
            return null
    }
}

/** Where a pre-redesign non-list tab segment (`runs`, `config`) lands now, or null. */
export function legacyInboxTabPath(tab: string | undefined): string | null {
    switch (tab) {
        case 'runs':
            return urls.inboxRuns()
        case 'config':
            return urls.inbox('settings')
        default:
            return null
    }
}
