import type { ExperimentListSegment } from '@/api/experiments'
import { formatClock, formatMonthDay } from '@/lib/dates'

import type { ExperimentConclusion, ExperimentRow, HeadlineResult } from './experimentModel'

// The words of the experiments list. Pure, so the copy for every row state is one place and testable.

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

export const SEGMENT_LABELS: Record<ExperimentListSegment, string> = {
    running: 'Running',
    complete: 'Done',
    draft: 'Drafts',
}

export const CONCLUSION_LABELS: Record<ExperimentConclusion, string> = {
    won: 'Won',
    lost: 'Lost',
    inconclusive: 'Inconclusive',
    stopped_early: 'Stopped early',
    invalid: 'Invalid',
}

/** `6.8k`, `19.5k`, `214`. */
export function compactCount(value: number): string {
    if (value >= 1_000_000) {
        return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
    }
    if (value >= 1000) {
        return `${(value / 1000).toFixed(1).replace(/\.0$/, '')}k`
    }
    return String(Math.round(value))
}

/** A relative change as `+12.4%` or `−14.0%`, with a real minus sign. */
export function signedPercent(fraction: number): string {
    const percent = fraction * 100
    const sign = percent > 0.05 ? '+' : percent < -0.05 ? '−' : ''
    return `${sign}${Math.abs(percent).toFixed(1)}%`
}

export function pValueText(pValue: number): string {
    return pValue < 0.001 ? '< 0.001' : pValue.toFixed(3)
}

/** A chance to win in a row, `> 99%` at the top, whole percents below. */
export function chanceText(chance: number): string {
    const percent = chance * 100
    return percent >= 99.5 ? '> 99%' : percent < 1 ? '< 1%' : `${Math.round(percent)}%`
}

/** `38 min`, `5 h`, `3 d`. */
export function ageText(ms: number): string {
    if (ms < HOUR) {
        return `${Math.max(1, Math.floor(ms / MINUTE))} min`
    }
    if (ms < DAY) {
        return `${Math.floor(ms / HOUR)} h`
    }
    return `${Math.floor(ms / DAY)} d`
}

function agoText(ms: number): string {
    return ms < MINUTE ? 'just now' : `${ageText(ms)} ago`
}

export type RowBadge = 'new' | 'paused' | 'frozen' | 'ship' | 'losing'

export const BADGE_LABELS: Record<RowBadge, string> = {
    new: 'New',
    paused: 'Paused',
    frozen: 'Frozen',
    ship: 'Ready to ship',
    losing: 'Losing',
}

function resultHeadline(row: ExperimentRow): HeadlineResult | null {
    return typeof row.headline === 'string' ? null : row.headline
}

export function rowBadge(row: ExperimentRow): RowBadge | null {
    if (row.status === 'draft' || row.status === 'complete') {
        return null
    }
    if (row.isNew) {
        return 'new'
    }
    if (row.status === 'paused') {
        return 'paused'
    }
    const headline = resultHeadline(row)
    if (headline?.kind === 'significant') {
        return headline.better ? 'ship' : 'losing'
    }
    return row.status === 'frozen' ? 'frozen' : null
}

/** How line 2 draws: `good` and `bad` lead with an icon, `quiet` is muted, `pending` dots the start. */
export type LineTone = 'good' | 'bad' | 'plain' | 'quiet' | 'pending'

export interface RowLine {
    tone: LineTone
    /** The leading word in the tone's color, such as "Significant" or the conclusion. */
    lead: string | null
    /** The rest, joined with ` · `, or with a space for a part that `glue`s to the one before. */
    parts: { text: string; strong?: boolean; glue?: boolean }[]
}

/** Days until the saved sample target at the pace so far, from the list's stored estimate. */
export function daysToTarget(row: ExperimentRow, now: number): number | null {
    const recommended = row.targetSampleSize
    const headline = resultHeadline(row)
    const exposures = headline?.exposures
    const started = row.startedAt ? Date.parse(row.startedAt) : Number.NaN
    if (!recommended || !exposures || Number.isNaN(started) || exposures >= recommended) {
        return null
    }
    const days = (now - started) / DAY
    const pace = days > 0 ? exposures / days : 0
    return pace > 0 ? Math.max(1, Math.ceil((recommended - exposures) / pace)) : null
}

export function rowLine(row: ExperimentRow, now: number): RowLine | 'loading' {
    if (row.status === 'complete') {
        const lead = row.conclusion ? CONCLUSION_LABELS[row.conclusion] : 'Ended'
        const shipped = row.shippedVariant ? `shipped ${row.shippedVariant}` : 'nothing shipped'
        return { tone: 'plain', lead, parts: [{ text: row.conclusion ? shipped : 'no conclusion recorded' }] }
    }
    if (row.status === 'draft') {
        const variants = row.variants.length ? [{ text: `${row.variants.length} variants` }] : []
        return { tone: 'quiet', lead: null, parts: [{ text: 'Not launched' }, ...variants] }
    }
    if (row.headline === 'loading') {
        return 'loading'
    }
    if (row.headline === 'error') {
        return { tone: 'quiet', lead: null, parts: [{ text: "Couldn't load results" }] }
    }
    if (row.headline === 'none') {
        return { tone: 'quiet', lead: null, parts: [{ text: 'No primary metric' }] }
    }
    const headline = row.headline
    const leader = headline.leader ?? ''
    switch (headline.kind) {
        case 'not_yet':
            return {
                tone: 'pending',
                lead: null,
                parts: [{ text: 'No results yet' }, ...(row.isNew ? [{ text: 'exposures arriving' }] : [])],
            }
        case 'significant': {
            const pValue = headline.pValue === undefined ? [] : [{ text: `p = ${pValueText(headline.pValue)}` }]
            return {
                tone: headline.better ? 'good' : 'bad',
                lead: 'Significant',
                parts: [
                    { text: leader },
                    { text: signedPercent(headline.delta ?? 0), strong: true, glue: leader !== '' },
                    ...pValue,
                ].filter((part) => part.text !== ''),
            }
        }
        case 'target':
            return { tone: 'plain', lead: null, parts: [{ text: 'Target reached' }, { text: 'no clear winner' }] }
        case 'leading':
            return {
                tone: 'plain',
                lead: null,
                parts:
                    headline.chanceToWin !== undefined
                        ? [
                              { text: `${leader} leading` },
                              { text: chanceText(headline.chanceToWin), strong: true },
                              { text: 'chance to win', glue: true },
                          ]
                        : [{ text: `${leader} leading` }, { text: `p = ${pValueText(headline.pValue ?? 1)}` }],
            }
        case 'needs_data': {
            const toGo = daysToTarget(row, now)
            return {
                tone: 'quiet',
                lead: null,
                parts: [
                    { text: 'Needs more data' },
                    ...(toGo === null ? [] : [{ text: `~${toGo} ${toGo === 1 ? 'day' : 'days'} to target` }]),
                ],
            }
        }
    }
}

function byPerson(row: ExperimentRow, myUuid: string | null): string | null {
    if (!row.createdBy) {
        return null
    }
    return myUuid !== null && row.createdBy.uuid === myUuid ? 'by you' : `by ${row.createdBy.name}`
}

export function rowMeta(row: ExperimentRow, now: number, myUuid: string | null): string {
    const headline = resultHeadline(row)
    const exposed = headline?.exposures === undefined ? null : `${compactCount(headline.exposures)} exposed`
    const variants = row.variants.length ? `${row.variants.length} variants` : null
    if (row.status === 'draft') {
        const created = `Created ${formatMonthDay(new Date(row.createdAt))}`
        const by = byPerson(row, myUuid)
        return [by ? `${created} ${by}` : created, `flag ${row.flagKey}`].join(' · ')
    }
    if (row.status === 'complete') {
        const ended = row.endedAt ? `ended ${formatMonthDay(new Date(row.endedAt))}` : null
        return [row.days === null ? null : `Ran ${row.days} d`, ended, exposed].filter(Boolean).join(' · ')
    }
    const started = row.startedAt ? Date.parse(row.startedAt) : Number.NaN
    const age = headline?.resultsAt ? now - Date.parse(headline.resultsAt) : Number.NaN
    const lead =
        row.isNew && !Number.isNaN(started)
            ? `Launched ${now - started < MINUTE ? 'just now' : agoText(now - started)}`
            : row.days === null
              ? null
              : `Running ${row.days} d`
    return [lead, variants, exposed, Number.isNaN(age) || row.isNew ? null : `${ageText(Math.max(0, age))} old`]
        .filter(Boolean)
        .join(' · ')
}

/** The status line under the title, or on the tabs header when pinned. */
export function listStatus(
    segment: ExperimentListSegment,
    state: { loading: boolean; oldestResultsAt: number | null; rowsSettled: boolean },
    now: number
): string {
    if (state.loading) {
        return 'Loading…'
    }
    if (segment === 'complete') {
        return 'Final results · ended experiments'
    }
    if (segment === 'draft') {
        return 'Not launched yet'
    }
    if (state.oldestResultsAt !== null) {
        const at = new Date(state.oldestResultsAt)
        return `Results from ${formatClock(at)} · updated ${agoText(Math.max(0, now - state.oldestResultsAt))}`
    }
    return state.rowsSettled ? 'Stored results' : 'Loading results…'
}

/** Line 2 as one string, for accessibility labels and tests. */
export function rowLineText(line: RowLine): string {
    const parts = line.parts.reduce<string>(
        (text, part) => (text === '' ? part.text : `${text}${part.glue ? ' ' : ' · '}${part.text}`),
        ''
    )
    return [line.lead, parts].filter(Boolean).join(' · ')
}

export interface EmptyCopy {
    title: string
    message: string
    action: { label: string; kind: 'drafts' | 'clear_search' } | null
}

export function emptyCopy(segment: ExperimentListSegment, search: string): EmptyCopy {
    const text = search.trim()
    if (text) {
        return {
            title: `No experiments match “${text}”`,
            message: 'Search looks at names and flag keys in this segment.',
            action: { label: 'Clear search', kind: 'clear_search' },
        }
    }
    switch (segment) {
        case 'running':
            return {
                title: 'No running experiments',
                message: 'Launch one from your drafts, or create one on the web.',
                action: { label: 'See drafts', kind: 'drafts' },
            }
        case 'complete':
            return {
                title: 'Nothing finished yet',
                message: 'Experiments you end or ship show up here with their conclusion.',
                action: null,
            }
        case 'draft':
            return {
                title: 'No drafts',
                message: 'Create experiments on the web. Drafts show up here so you can launch them.',
                action: null,
            }
    }
}
