import {
    pickReusableExport,
    REPLAY_VIDEO_RENDER_TIMEOUT_MS,
    type ReplayVideoExport,
    type ReplayVideoRender,
} from '@/api/replayVideo'
import { serverNow } from '@/api/serverClock'
import { plural, truncate } from '@/model/adapters/text'

import type { SessionSummary } from '../replayModel'
import { formatOffset } from '../sessionAdapters'
import type {
    FeedEvent,
    FeedEventKind,
    FeedItem,
    FeedSource,
    FeedTimeline,
    Moment,
    MomentKind,
    MomentWindow,
} from './feedModel'

function text(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

function positive(value: unknown): number | null {
    const number = typeof value === 'string' ? Number(value) : value
    return typeof number === 'number' && Number.isFinite(number) && number > 0 ? number : null
}

export function firstText(value: unknown): string | null {
    if (Array.isArray(value)) {
        return value.map(text).find((item): item is string => item !== null) ?? null
    }
    if (typeof value === 'string' && value.startsWith('[')) {
        try {
            return firstText(JSON.parse(value) as unknown)
        } catch {
            return null
        }
    }
    return text(value)
}

/** The Vision title when the recording has one, else what it did. */
export function itemTitle(item: FeedItem): string {
    if (item.summary?.title) {
        return item.summary.title
    }
    const { clickCount, consoleErrorCount } = item.recording
    return ['Recording', plural(clickCount, 'click'), consoleErrorCount ? plural(consoleErrorCount, 'error') : null]
        .filter(Boolean)
        .join(' · ')
}

function kindOf(event: string): FeedEventKind | null {
    switch (event) {
        case '$pageview':
        case '$screen':
            return 'pageview'
        case '$autocapture':
            return 'click'
        case '$rageclick':
            return 'rageclick'
        case '$dead_click':
            return 'deadclick'
        case '$exception':
            return 'exception'
        default:
            return event.startsWith('$') ? null : 'custom'
    }
}

// Element, page and error texts come from the customer's site, so they are only ever shown as plain text.
function quoted(value: string | null): string {
    return value ? ` on “${truncate(value, 40)}”` : ''
}

function eventLabel(kind: FeedEventKind, event: string, target: string | null, detail: string | null): string {
    switch (kind) {
        case 'pageview':
            return target ? `Viewed ${truncate(target, 48)}` : 'Viewed a page'
        case 'click':
            return target ? `Clicked “${truncate(target, 40)}”` : 'Clicked'
        case 'rageclick':
            return `Rage click${quoted(target)}`
        case 'deadclick':
            return `Dead click${quoted(target)}`
        case 'exception':
            return detail ? `${target ?? 'Error'}: ${truncate(detail, 60)}` : (target ?? 'Error')
        case 'custom':
            return event
    }
}

export function feedTimeline(rows: readonly unknown[][], startTime: string): FeedTimeline {
    const start = new Date(startTime).getTime()
    const events: FeedEvent[] = []
    let browser: string | null = null
    let os: string | null = null
    let viewport: FeedTimeline['viewport'] = null
    let lastPage: string | null = null
    rows.forEach((row, index) => {
        const [
            timestamp,
            eventName,
            pathname,
            screenName,
            elementTexts,
            types,
            values,
            rowBrowser,
            rowOs,
            vw,
            vh,
            sw,
            sh,
        ] = row
        const at = text(timestamp)
        const event = text(eventName)
        const kind = event ? kindOf(event) : null
        if (!at || !event || !kind) {
            return
        }
        browser ??= text(rowBrowser)
        os ??= text(rowOs)
        if (!viewport) {
            const width = positive(vw) ?? positive(sw)
            const height = positive(vh) ?? positive(sh)
            viewport = width && height ? { width, height } : null
        }
        const page = text(screenName) ?? text(pathname)
        if (kind === 'pageview') {
            // A single-page app can send the same page view twice in a row.
            if (page !== null && page === lastPage) {
                return
            }
            lastPage = page
        }
        const target =
            kind === 'pageview'
                ? page
                : kind === 'exception'
                  ? firstText(types)
                  : kind === 'custom'
                    ? null
                    : firstText(elementTexts)
        const detail = kind === 'exception' ? firstText(values) : null
        events.push({
            key: `${index}:${at}`,
            kind,
            seconds: Math.max(0, (new Date(at).getTime() - start) / 1000),
            label: eventLabel(kind, event, target, detail),
            target: kind === 'custom' ? event : target,
        })
    })
    return { events, browser, os, viewport }
}

export const MERGE_SECONDS = 20
const PROBLEM_EVENT = /fail|error|declin|reject|timeout|denied/i

interface Anchor {
    kind: MomentKind
    seconds: number
    target: string | null
    /** The event's own label; for an error it carries the message, which says more than a type such as `Error`. */
    label: string | null
}

function anchorsFor(timeline: FeedTimeline, summary: SessionSummary | null, source: FeedSource): Anchor[] {
    const fromEvents = timeline.events.flatMap((event): Anchor[] => {
        const wanted =
            source === 'rage'
                ? event.kind === 'rageclick'
                : source === 'errors'
                  ? event.kind === 'exception'
                  : event.kind === 'rageclick' ||
                    event.kind === 'exception' ||
                    (event.kind === 'custom' && PROBLEM_EVENT.test(event.target ?? ''))
        if (!wanted) {
            return []
        }
        const kind: MomentKind =
            event.kind === 'rageclick' ? 'rageclick' : event.kind === 'exception' ? 'exception' : 'custom'
        return [{ kind, seconds: event.seconds, target: event.target, label: event.label }]
    })
    const key = summary?.keyMomentMs
    if ((source === 'newest' || source === 'highlights') && typeof key === 'number') {
        fromEvents.push({ kind: 'key', seconds: key / 1000, target: keyChapterTitle(summary, key), label: null })
    }
    return fromEvents.sort((a, b) => a.seconds - b.seconds)
}

function keyChapterTitle(summary: SessionSummary | null, keyMs: number): string | null {
    const chapter = summary?.chapters.find(
        (item) => item.startMs <= keyMs && (item.endMs === null || keyMs < item.endMs)
    )
    return chapter?.title ?? null
}

function groupLabel(group: readonly Anchor[]): string {
    const problems = group.filter((anchor) => anchor.kind !== 'key')
    if (problems.length === 0) {
        const key = group[0]
        return key?.target ? `Key moment: ${truncate(key.target, 48)}` : 'Key moment'
    }
    const first = problems[0] as Anchor
    const head = (() => {
        if (first.kind === 'rageclick') {
            const same = problems.filter((anchor) => anchor.kind === 'rageclick' && anchor.target === first.target)
            return same.length > 1
                ? `Rage clicks ×${same.length}${quoted(first.target)}`
                : `Rage click${quoted(first.target)}`
        }
        if (first.kind === 'exception') {
            return first.label ? truncate(first.label, 52) : 'An error'
        }
        return first.target ? `“${truncate(first.target, 40)}” event` : 'Custom event'
    })()
    const later = problems.find((anchor) => anchor.kind !== first.kind)
    if (!later) {
        return head
    }
    const tail =
        later.kind === 'exception'
            ? 'an error'
            : later.kind === 'rageclick'
              ? 'a rage click'
              : later.target
                ? `“${truncate(later.target, 32)}”`
                : null
    return tail ? `${head}, then ${tail}` : head
}

export function feedMoments(
    timeline: FeedTimeline,
    summary: SessionSummary | null,
    durationSeconds: number,
    settings: MomentWindow,
    source: FeedSource
): Moment[] {
    const anchors = anchorsFor(timeline, summary, source)
    const groups: Anchor[][] = []
    for (const anchor of anchors) {
        const last = groups.at(-1)
        const previous = last?.at(-1)
        if (last && previous && anchor.seconds - previous.seconds < MERGE_SECONDS) {
            last.push(anchor)
        } else {
            groups.push([anchor])
        }
    }
    const length = Math.max(5, Math.min(durationSeconds, settings.momentSeconds))
    const window = (anchorSeconds: number, lastSeconds: number): { startSeconds: number; endSeconds: number } => {
        const start = Math.max(0, Math.min(anchorSeconds - settings.leadInSeconds, durationSeconds - length))
        const end = Math.min(durationSeconds, Math.max(start + length, Math.min(lastSeconds + 6, start + 45)))
        return { startSeconds: start, endSeconds: Math.max(end, start + 1) }
    }
    if (groups.length === 0) {
        const first = timeline.events.find((event) => event.kind === 'click')?.seconds ?? 0
        return [{ key: 'start', kind: 'start', anchorSeconds: first, label: 'From the start', ...window(first, first) }]
    }
    return groups.map((group, index) => {
        const lead = group.find((anchor) => anchor.kind !== 'key') ?? (group[0] as Anchor)
        const anchorSeconds = Math.min(...group.map((anchor) => anchor.seconds))
        const lastSeconds = Math.max(...group.map((anchor) => anchor.seconds))
        return {
            key: `${index}:${Math.round(anchorSeconds)}`,
            kind: lead.kind,
            anchorSeconds,
            label: groupLabel(group),
            ...window(anchorSeconds, lastSeconds),
        }
    })
}

/** A whole recording starts a lead-in before its key moment, or its first problem, else at the beginning. */
export function sessionStartSeconds(
    moments: readonly Moment[],
    summary: SessionSummary | null,
    settings: MomentWindow
): number {
    const key = summary?.keyMomentMs
    const anchor =
        typeof key === 'number' ? key / 1000 : moments.find((moment) => moment.kind !== 'start')?.anchorSeconds
    return anchor === undefined ? 0 : Math.max(0, anchor - settings.leadInSeconds)
}

const MIN_WIDTH = 400
const MIN_HEIGHT = 300
const MAX_WIDTH = 3840
const MAX_HEIGHT = 2160

function even(value: number): number {
    return Math.max(2, Math.round(value / 2) * 2)
}

/**
 * Renders at the recording's own shape instead of a fixed 1400 x 600 strip, so a phone session fills the screen and a
 * desktop page has no baked-in bars. Phone screens render at 2x. The result stays inside the server's bounds.
 */
export function renderViewport(viewport: FeedTimeline['viewport']): Pick<ReplayVideoRender, 'width' | 'height'> {
    if (!viewport) {
        return { width: 1440, height: 900 }
    }
    let scale = viewport.width < 720 ? 2 : 1
    scale = Math.max(scale, MIN_WIDTH / viewport.width, MIN_HEIGHT / viewport.height)
    scale = Math.min(scale, MAX_WIDTH / viewport.width, MAX_HEIGHT / viewport.height)
    return { width: even(viewport.width * scale), height: even(viewport.height * scale) }
}

export type RenderSpec =
    | { kind: 'full'; sessionId: string; durationSeconds: number }
    | { kind: 'clip'; sessionId: string; durationSeconds: number; startSeconds: number; endSeconds: number }

export function renderKey(spec: RenderSpec): string {
    return spec.kind === 'full'
        ? `${spec.sessionId}:full`
        : `${spec.sessionId}:clip:${Math.floor(spec.startSeconds)}-${Math.ceil(spec.endSeconds)}`
}

function timeOf(iso: string | null): number {
    return iso === null ? Number.NaN : Date.parse(iso)
}

function usable(asset: ReplayVideoExport, now: number): 'ready' | 'rendering' | null {
    if (asset.exception) {
        return null
    }
    if (asset.has_content) {
        return asset.expires_after === null || timeOf(asset.expires_after) > now ? 'ready' : null
    }
    const created = timeOf(asset.created_at)
    return Number.isNaN(created) || now - created < REPLAY_VIDEO_RENDER_TIMEOUT_MS ? 'rendering' : null
}

function coversClip(asset: ReplayVideoExport, startSeconds: number, endSeconds: number): boolean {
    const context = asset.export_context
    const from = context?.start_offset_s
    const to = context?.end_offset_s
    return (
        typeof from === 'number' &&
        typeof to === 'number' &&
        from <= Math.floor(startSeconds) &&
        to >= Math.ceil(endSeconds)
    )
}

/**
 * The export that answers `spec` without a new render. A clip takes, in order: a finished whole-recording video, a
 * finished clip that covers it, a clip still rendering, then a whole recording still rendering. One video then serves
 * every moment it covers, and nothing renders twice.
 */
export function pickExportFor(
    exports: readonly ReplayVideoExport[],
    spec: RenderSpec,
    now: number = serverNow()
): ReplayVideoExport | null {
    const full = pickReusableExport(exports, spec.durationSeconds, now)
    if (spec.kind === 'full') {
        return full
    }
    if (full?.has_content) {
        return full
    }
    const clips = exports
        .filter((asset) => coversClip(asset, spec.startSeconds, spec.endSeconds))
        .sort((a, b) => timeOf(b.created_at) - timeOf(a.created_at))
    return (
        clips.find((asset) => usable(asset, now) === 'ready') ??
        clips.find((asset) => usable(asset, now) === 'rendering') ??
        full
    )
}

export function hasReadyVideo(exports: readonly ReplayVideoExport[], now: number = serverNow()): boolean {
    return exports.some((asset) => usable(asset, now) === 'ready')
}

export function compactDuration(seconds: number): string {
    const total = Math.max(0, Math.round(seconds))
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const rest = total % 60
    if (hours > 0) {
        return `${hours}h ${minutes}m`
    }
    return minutes > 0 ? `${minutes}m ${String(rest).padStart(2, '0')}s` : `${rest}s`
}

export function feedMetaLine(props: {
    timeline: FeedTimeline | null
    durationSeconds: number
    keyMomentMs: number | null
}): string {
    return [
        props.timeline?.browser,
        props.timeline?.os,
        compactDuration(props.durationSeconds),
        props.keyMomentMs !== null ? `key ${formatOffset(props.keyMomentMs)}` : null,
    ]
        .filter((part): part is string => Boolean(part))
        .join(' · ')
}
