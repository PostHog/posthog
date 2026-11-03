import type {
    BreakdownValueApi,
    ErrorsWindow,
    IssueAssigneeApi,
    IssueBreakdownApi,
    IssueEventApi,
    IssueListItemApi,
    IssueStatusApi,
    IssueTrendApi,
    SpikeEventApi,
    StackFrameApi,
} from '@/api/errorTracking'
import type { ProjectScope } from '@/api/reports'
import { formatRelativeAgo } from '@/lib/dates'

const HOUR_MS = 60 * 60_000
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const WINDOW_MS: Record<ErrorsWindow, number> = { '24h': 24 * HOUR_MS, '7d': 7 * 24 * HOUR_MS }

/** Checks an issue id from a route or a link before it reaches an API path. */
export function isIssueId(value: string): boolean {
    return UUID.test(value)
}

export type IssueFilter = 'all' | 'new' | 'spiking' | 'mine'
export type IssueBadge = 'new' | 'spiking'

export type IssueAssignee =
    | { kind: 'none' }
    | { kind: 'me' }
    | { kind: 'user'; id: number }
    | { kind: 'role'; id: string }

export interface IssueRow {
    id: string
    title: string
    detail: string | null
    status: IssueStatusApi
    users: number
    occurrences: number
    sessions: number
    firstSeen: string | null
    lastSeen: string | null
    library: string | null
    assignee: IssueAssignee
    volume: number[]
    isNew: boolean
    isSpiking: boolean
    badge: IssueBadge | null
}

export interface IssueFrame {
    functionName: string
    location: string | null
}

export interface SessionSample {
    sessionId: string
    at: string
    platform: string | null
}

export interface BreakdownRow {
    key: 'location' | 'browser' | 'os' | 'app_version'
    label: string
    values: { value: string; percent: number }[]
}

/** The web's `ISSUE_STATUS_CONFIG` labels in `products/error_tracking/frontend/components/Indicators.tsx`. */
export const ISSUE_STATUS_LABELS: Record<IssueStatusApi, string> = {
    active: 'Active',
    resolved: 'Resolved',
    suppressed: 'Suppressed',
    archived: 'Archived',
    pending_release: 'Pending release',
}

export function statusLabel(status: string): string {
    return ISSUE_STATUS_LABELS[status as IssueStatusApi] ?? 'Unknown'
}

export function agoPhrase(iso: string, now: Date): string {
    const ago = formatRelativeAgo(iso, now)
    return ago === 'Just now' ? 'just now' : ago
}

export function windowParam(value: string | string[] | undefined): ErrorsWindow {
    const first = Array.isArray(value) ? value[0] : value
    return first === '7d' ? '7d' : '24h'
}

export const WINDOW_LABELS: Record<ErrorsWindow, string> = { '24h': 'the last 24 hours', '7d': 'the last 7 days' }

export function windowStart(window: ErrorsWindow, now: Date): Date {
    return new Date(now.getTime() - WINDOW_MS[window])
}

export function isNewInWindow(firstSeen: string | null | undefined, window: ErrorsWindow, now: Date): boolean {
    if (!firstSeen) {
        return false
    }
    const at = Date.parse(firstSeen)
    return Number.isFinite(at) && at >= windowStart(window, now).getTime()
}

export function spikingIssueIds(events: readonly SpikeEventApi[]): Set<string> {
    return new Set(events.map((event) => event.issue.id))
}

/** A new issue is never also called spiking: everything it did happened inside the window. */
export function badgeFor(isNew: boolean, spiking: boolean): IssueBadge | null {
    if (isNew) {
        return 'new'
    }
    return spiking ? 'spiking' : null
}

export function highlightStart(values: readonly number[], badge: IssueBadge | null): number | null {
    if (!badge || values.length === 0) {
        return null
    }
    if (badge === 'new') {
        const first = values.findIndex((value) => value > 0)
        return first === -1 ? null : first
    }
    const sorted = [...values].sort((a, b) => a - b)
    const middle = Math.floor(sorted.length / 2)
    const median = sorted.length % 2 ? (sorted[middle] ?? 0) : ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2
    let start = values.length
    while (start > 0 && (values[start - 1] ?? 0) > median) {
        start--
    }
    return start === values.length ? values.length - 1 : start
}

export function assigneeFrom(assignee: IssueAssigneeApi | null | undefined, myUserId: number | null): IssueAssignee {
    if (!assignee || assignee.id === null || assignee.id === undefined) {
        return { kind: 'none' }
    }
    if (assignee.type === 'role') {
        return { kind: 'role', id: String(assignee.id) }
    }
    const id = Number(assignee.id)
    if (!Number.isFinite(id)) {
        return { kind: 'none' }
    }
    return myUserId !== null && id === myUserId ? { kind: 'me' } : { kind: 'user', id }
}

function count(value: number | undefined): number {
    return typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : 0
}

export interface IssueRowContext {
    window: ErrorsWindow
    now: Date
    spiking: ReadonlySet<string>
    myUserId: number | null
}

export function issueRowFrom(api: IssueListItemApi, context: IssueRowContext): IssueRow {
    const aggregations = api.aggregations ?? {}
    const firstSeen = api.first_seen ?? null
    return {
        id: api.id,
        title: api.name?.trim() || 'Unnamed error',
        detail: api.description?.trim() || null,
        status: api.status && api.status in ISSUE_STATUS_LABELS ? (api.status as IssueStatusApi) : 'active',
        users: count(aggregations.users),
        occurrences: count(aggregations.occurrences),
        sessions: count(aggregations.sessions),
        firstSeen,
        lastSeen: api.last_seen ?? null,
        library: api.library ?? null,
        assignee: assigneeFrom(api.assignee, context.myUserId),
        volume: (aggregations.volumeRange ?? []).map((value) => (Number.isFinite(value) ? value : 0)),
        isNew: isNewInWindow(firstSeen, context.window, context.now),
        isSpiking: context.spiking.has(api.id),
        badge: badgeFor(isNewInWindow(firstSeen, context.window, context.now), context.spiking.has(api.id)),
    }
}

/** New and Spiking narrow the loaded list on the device. Mine is a server filter, so its rows are all the viewer's. */
export function filterRows(rows: readonly IssueRow[], filter: IssueFilter): IssueRow[] {
    switch (filter) {
        case 'new':
            return rows.filter((row) => row.isNew)
        case 'spiking':
            return rows.filter((row) => row.isSpiking)
        case 'mine':
            return rows.filter((row) => row.assignee.kind === 'me')
        default:
            return [...rows]
    }
}

function basename(path: string): string {
    const parts = path.split(/[\\/]/).filter(Boolean)
    return parts[parts.length - 1] ?? path
}

function frameFrom(frame: StackFrameApi): IssueFrame {
    const name = [frame.resolved_name, frame.function, frame.mangled_name].find(
        (value): value is string => typeof value === 'string' && value.trim() !== '' && value !== '?'
    )
    const file = frame.source ? basename(frame.source) : null
    const line = typeof frame.line === 'number' ? frame.line : null
    return {
        functionName: name ?? 'Anonymous function',
        location: file ? (line === null ? file : `${file}:${line}`) : null,
    }
}

export interface IssueFrames {
    /** Innermost first. */
    frames: IssueFrame[]
    total: number
}

/**
 * The innermost in-app frames of the newest event that has a stack. Frames run from the outermost call to the one that
 * raised, as the backend's `build_top_in_app_frame` reads them.
 */
export function issueFrames(events: readonly IssueEventApi[], max: number): IssueFrames {
    for (const event of events) {
        const inApp = (event.properties?.$exception_list ?? [])
            .flatMap((exception) => exception.stacktrace?.frames ?? [])
            .filter((frame) => frame.in_app !== false)
        if (inApp.length > 0) {
            return { frames: inApp.reverse().slice(0, max).map(frameFrom), total: inApp.length }
        }
    }
    return { frames: [], total: 0 }
}

export function sampleSessions(events: readonly IssueEventApi[], max: number): SessionSample[] {
    const seen = new Set<string>()
    const samples: SessionSample[] = []
    for (const event of events) {
        const sessionId = event.properties?.$session_id?.trim()
        if (!sessionId || !event.timestamp || seen.has(sessionId)) {
            continue
        }
        seen.add(sessionId)
        const { $browser: browser, $os: os } = event.properties ?? {}
        samples.push({
            sessionId,
            at: event.timestamp,
            platform: browser && os ? `${browser} on ${os}` : browser || os || null,
        })
        if (samples.length === max) {
            break
        }
    }
    return samples
}

const BREAKDOWN_VALUES = 3

export function breakdownRows(breakdown: IssueBreakdownApi | null | undefined): BreakdownRow[] {
    if (!breakdown || breakdown.occurrences <= 0) {
        return []
    }
    const total = breakdown.occurrences
    const top = breakdown.top_values
    // Web SDKs send a path, backend SDKs only a URL, and mobile SDKs a screen name.
    const location = top.path?.length
        ? { label: 'Path', values: top.path }
        : top.url?.length
          ? { label: 'URL', values: top.url }
          : { label: 'Screen', values: top.screen }
    const dimensions: { key: BreakdownRow['key']; label: string; values: BreakdownValueApi[] | undefined }[] = [
        { key: 'location', ...location },
        { key: 'browser', label: 'Browser', values: top.browser },
        { key: 'os', label: 'OS', values: top.os },
        { key: 'app_version', label: 'App version', values: top.app_version },
    ]
    return dimensions.flatMap(({ key, label, values }) =>
        values?.length
            ? [
                  {
                      key,
                      label,
                      values: values.slice(0, BREAKDOWN_VALUES).map(({ value, count: n }) => ({
                          value,
                          percent: Math.min(100, Math.round((n / total) * 100)),
                      })),
                  },
              ]
            : []
    )
}

export function issueWebUrl(scope: ProjectScope | null, issueId: string): string | undefined {
    return scope ? `${scope.host}/project/${scope.projectId}/error_tracking/${encodeURIComponent(issueId)}` : undefined
}

export interface TrendCaption {
    text: string
    rising: boolean
}

export function trendCaption(trend: IssueTrendApi | undefined): TrendCaption | null {
    switch (trend?.direction) {
        case 'new':
            return { text: 'New in this window', rising: true }
        case 'increasing':
            return {
                text: trend.change_percent === undefined ? 'Rising' : `Up ${trend.change_percent}%`,
                rising: true,
            }
        case 'decreasing':
            return {
                text: trend.change_percent === undefined ? 'Falling' : `Down ${Math.abs(trend.change_percent)}%`,
                rising: false,
            }
        case 'stable':
            return { text: 'Steady', rising: false }
        default:
            return null
    }
}

export interface EmptyCopy {
    title: string
    message: string
    action: { label: string; kind: 'window' | 'clear_filter' | 'retry_spikes' } | null
}

export interface IssueListProgress {
    hasMore: boolean
    spikesLoading: boolean
    spikesFailed: boolean
}

export function emptyCopy(filter: IssueFilter, window: ErrorsWindow, progress?: IssueListProgress): EmptyCopy {
    if (filter === 'spiking' && progress?.spikesLoading) {
        return {
            title: 'Checking for spikes…',
            message: 'Your issues are loaded. Spike information is still loading.',
            action: null,
        }
    }
    if (filter === 'spiking' && progress?.spikesFailed) {
        return {
            title: "Couldn't check for spikes",
            message: 'Try again to check which issues are spiking.',
            action: { label: 'Try again', kind: 'retry_spikes' },
        }
    }
    if (progress?.hasMore && (filter === 'new' || filter === 'spiking')) {
        return {
            title: 'No matches in loaded issues',
            message: 'Load more issues to keep checking, or choose another filter.',
            action: null,
        }
    }
    const range = WINDOW_LABELS[window]
    const showAll = { label: 'Show all active issues', kind: 'clear_filter' } as const
    switch (filter) {
        case 'new':
            return {
                title: `No new errors in ${range}`,
                message: 'Issues that first appear in this window show up here.',
                action: showAll,
            }
        case 'spiking':
            return {
                title: `Nothing is spiking in ${range}`,
                message: 'Issues show up here when PostHog detects a spike in their occurrences.',
                action: showAll,
            }
        case 'mine':
            return {
                title: 'No active issues assigned to you',
                message: 'Assign an issue to yourself from its screen and it shows up here.',
                action: showAll,
            }
        default:
            return {
                title: `No active errors in ${range}`,
                message:
                    window === '24h'
                        ? 'Nothing to triage right now. Check the last 7 days for older issues.'
                        : 'Nothing to triage right now. Resolved and suppressed issues stay on the web.',
                action: window === '24h' ? { label: 'Show the last 7 days', kind: 'window' } : null,
            }
    }
}
