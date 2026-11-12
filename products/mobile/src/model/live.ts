export type LiveBreakdownKind = 'devices' | 'browsers' | 'countries'

/** What the top list counts: pageviews by path, or screen views by screen name for a project with app events only. */
export type LivePathsMode = 'pages' | 'screens'

/**
 * What the project sends. `app_only`: events but no pageviews, as from a mobile SDK. `quiet`: no events in the window.
 * `not_set_up`: the project has never ingested an event.
 */
export type LiveProjectState = 'web' | 'app_only' | 'quiet' | 'not_set_up'

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

/** Every country with visitors, most first, for the world map. The Countries breakdown keeps only the top six. */
export interface LiveWorld {
    total: number
    countries: LiveBreakdownRow[]
    /** Visitors per ISO 3166-1 alpha-2 code, as the map reads them. */
    counts: Readonly<Record<string, number>>
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
    /** What `topPages` counts. Null until the first answer. */
    topPagesMode: LivePathsMode | null
    topReferrers: LiveRankedRow[] | null
    devices: LiveBreakdown | null
    browsers: LiveBreakdown | null
    countries: LiveBreakdown | null
    world: LiveWorld | null
    events: LiveEventRow[] | null
    usersOnline: number | null
}

export const EMPTY_LIVE_SNAPSHOT: LiveSnapshot = {
    activity: null,
    topPages: null,
    topPagesMode: null,
    topReferrers: null,
    devices: null,
    browsers: null,
    countries: null,
    world: null,
    events: null,
    usersOnline: null,
}
