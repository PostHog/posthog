import { formatRelativeAgo } from '@/lib/dates'
import { truncate } from '@/model/adapters/text'

import { compactDuration, firstText, itemTitle } from './feedAdapters'
import type { FeedItem, FeedSource } from './feedModel'
import { clusterTicks } from './scrubberMarks'

/** What a recording's row leads with: the icon and the color of its reason line. */
export type RowReason = 'rage' | 'error' | 'highlight' | 'none'

export interface SessionSignals {
    rage: { seconds: number; target: string | null }[]
    errors: { seconds: number; type: string | null; value: string | null }[]
}

export interface StripMark {
    key: string
    /** 0 at the recording's start, 1 at its end. */
    at: number
    kind: 'rage' | 'error'
}

export interface SessionRowModel {
    reason: RowReason
    title: string
    /** The strongest signal in the recording, or null when it has none to show. */
    reasonText: string | null
    person: string
    /** Length and age, which stay whole when a long person label is cut short. */
    details: string
    marks: StripMark[]
}

/** The strip draws at most one mark per 6 points of this width. */
const STRIP_WIDTH = 240

/** Groups the batched signal rows (`FEED_SIGNAL_COLUMNS`) by recording, as seconds from each recording's start. */
export function parseSignals(
    rows: readonly unknown[][],
    startsMs: ReadonlyMap<string, number>
): Map<string, SessionSignals> {
    const bySession = new Map<string, SessionSignals>()
    for (const [sessionId, timestamp, event, texts, types, values] of rows) {
        const start = typeof sessionId === 'string' ? startsMs.get(sessionId) : undefined
        const at = typeof timestamp === 'string' ? Date.parse(timestamp) : Number.NaN
        if (start === undefined || Number.isNaN(at)) {
            continue
        }
        const seconds = Math.max(0, (at - start) / 1000)
        const signals = bySession.get(sessionId as string) ?? { rage: [], errors: [] }
        if (event === '$rageclick') {
            signals.rage.push({ seconds, target: firstText(texts) })
        } else if (event === '$exception') {
            signals.errors.push({ seconds, type: firstText(types), value: firstText(values) })
        }
        bySession.set(sessionId as string, signals)
    }
    return bySession
}

// Element and error texts come from the customer's site, so they are only ever shown as plain text.
function rageText(rage: SessionSignals['rage']): string | null {
    if (rage.length === 0) {
        return null
    }
    const counts = new Map<string | null, number>()
    for (const click of rage) {
        counts.set(click.target, (counts.get(click.target) ?? 0) + 1)
    }
    let target: string | null = null
    let most = 0
    for (const [key, count] of counts) {
        if (count > most) {
            target = key
            most = count
        }
    }
    const on = target ? ` on “${truncate(target, 40)}”` : ''
    return `Rage click${on}${most > 1 ? ` ×${most}` : ''}`
}

function errorText(errors: SessionSignals['errors']): string | null {
    const first = errors[0]
    if (!first) {
        return null
    }
    if (first.type && first.value) {
        return `${first.type}: ${truncate(first.value, 80)}`
    }
    return first.type ?? (first.value ? truncate(first.value, 80) : 'An error')
}

/**
 * One row of the Sessions list. The reason line is the strongest signal for the chosen source: the rage click that
 * repeats most, the first error, or the reason Replay Vision picked the recording. On Newest an error comes before a
 * rage click, then the Vision reason.
 */
export function sessionRow(
    item: FeedItem,
    signals: SessionSignals | undefined,
    source: FeedSource,
    now: Date
): SessionRowModel {
    const { recording, summary } = item
    const rage = rageText(signals?.rage ?? [])
    const error = errorText(signals?.errors ?? [])
    const picked = summary?.notabilityReason ?? null
    const order: [RowReason, string | null][] =
        source === 'rage'
            ? [['rage', rage]]
            : source === 'errors'
              ? [['error', error]]
              : source === 'highlights'
                ? [
                      ['highlight', picked],
                      ['error', error],
                      ['rage', rage],
                  ]
                : [
                      ['error', error],
                      ['rage', rage],
                      ['highlight', picked],
                  ]
    const [reason, reasonText] = order.find(([, text]) => text !== null) ?? ['none', null]
    const duration = Math.max(1, recording.durationSeconds)
    const ticks = [
        ...(signals?.rage ?? []).map((click, index) => ({
            key: `r${index}`,
            seconds: click.seconds,
            kind: 'rage' as const,
            label: '',
        })),
        ...(signals?.errors ?? []).map((error, index) => ({
            key: `e${index}`,
            seconds: error.seconds,
            kind: 'error' as const,
            label: '',
        })),
    ]
    const marks = clusterTicks(ticks, 0, duration, STRIP_WIDTH).map((tick) => ({
        key: tick.key,
        at: Math.min(1, tick.seconds / duration),
        kind: tick.kind === 'error' ? ('error' as const) : ('rage' as const),
    }))
    const ago = recording.startedAt ? formatRelativeAgo(recording.startedAt, now) : null
    return {
        reason,
        title: summary?.title ?? recording.startPath ?? itemTitle(item),
        reasonText,
        person: recording.personLabel,
        details: [compactDuration(recording.durationSeconds), ago].filter(Boolean).join(' · '),
        marks,
    }
}
