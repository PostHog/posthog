export type LiveBreakdownKind = 'devices' | 'browsers' | 'countries'

/** One minute of the active users chart. `at` is the minute's start, epoch milliseconds. */
export interface LiveMinute {
    at: number
    users: number
    /** Ids the window shows first in this minute. */
    newUsers: number
    /** Ids the window already showed in an earlier minute. */
    returningUsers: number
    pageviews: number
}

export interface LiveActivity {
    minutes: LiveMinute[]
    uniqueVisitors: number
    pageviews: number
}

export interface LiveRankedRow {
    key: string
    label: string
    views: number
    /** Share of the window's pageviews, 0 to 100. */
    percent: number
    /** Places the row moved since the previous read, positive when it moved up. Null when new or unmoved. */
    rankDelta: number | null
    /** The "Direct / None" referrer, which the table shows in italics. */
    direct: boolean
}

export interface LiveBreakdownRow {
    key: string
    label: string
    flag: string | null
    count: number
    /** Share of the card's total, 0 to 100. */
    percent: number
}

export interface LiveBreakdown {
    statLabel: string
    total: number
    rows: LiveBreakdownRow[]
}

export type LiveEventKind = 'pageview' | 'screen' | 'other'

export interface LiveEventRow {
    id: string
    event: string
    label: string
    kind: LiveEventKind
    distinctId: string
    /** What the row shows under the name: the path, else the screen name, else the URL. */
    place: string | null
    url: string | null
    sessionId: string | null
    /** Epoch milliseconds. NaN when the response had no readable time. */
    at: number
}

/** Each part is null until its first good read, and keeps its last good value when a later read of it fails. */
export interface LiveSnapshot {
    activity: LiveActivity | null
    topPages: LiveRankedRow[] | null
    topReferrers: LiveRankedRow[] | null
    devices: LiveBreakdown | null
    browsers: LiveBreakdown | null
    countries: LiveBreakdown | null
    events: LiveEventRow[] | null
    usersOnline: number | null
}

export const EMPTY_LIVE_SNAPSHOT: LiveSnapshot = {
    activity: null,
    topPages: null,
    topReferrers: null,
    devices: null,
    browsers: null,
    countries: null,
    events: null,
    usersOnline: null,
}
