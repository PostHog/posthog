import type {
    ExperimentApi,
    ExperimentExposureResponseApi,
    ExperimentHealthApi,
    ExperimentResultsRunApi,
    ExperimentRunningTimeTargetApi,
} from '@/api/experiments'
import { calendarDaysBetween, formatClock, formatMonthDay } from '@/lib/dates'
import { isRecord } from '@/lib/records'

import {
    type ExperimentDifferenceType,
    type ExperimentMethod,
    type ExperimentStatus,
    freshnessOf,
    leaderOf,
    type MetricEntry,
    type MetricGoal,
    type MetricRole,
    methodOf,
    metricResultOf,
    orderedMetricsOf,
    type ResultMetric,
    resultOf,
    shippedVariantOf,
} from './experimentModel'

// Pure view models for the experiment detail. Relative numbers are fractions (0.124 is +12.4%), as in experimentModel.

const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS

/** A launch this recent shows the Watching card, which re-reads exposures while the screen is open. */
export const WATCH_WINDOW_MS = 2 * HOUR_MS
/** The web's sample ratio mismatch threshold (`exposureHealth.ts`). */
export const SAMPLE_RATIO_P_VALUE = 0.001
/** Results older than these read amber, then red, on the status card. */
export const AGING_MS = 6 * HOUR_MS
export const STALE_MS = 12 * HOUR_MS

const MINUS = '−'
const NBSP = ' '

// ---------- Numbers ----------

/** Thousands separators without Intl, so Hermes, the web build and Jest print the same text. */
export function formatCount(value: number): string {
    const rounded = Math.round(value)
    const sign = rounded < 0 ? MINUS : ''
    return sign + String(Math.abs(rounded)).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

function formatDecimal(value: number, digits: number): string {
    const fixed = Math.abs(value).toFixed(digits)
    const [whole, fraction] = fixed.split('.')
    const grouped = (whole ?? '0').replace(/\B(?=(\d{3})+(?!\d))/g, ',')
    return (value < 0 ? MINUS : '') + (fraction ? `${grouped}.${fraction}` : grouped)
}

/**
 * How a change against the baseline reads. `relative` is a fraction of the baseline's value. An absolute change is in
 * the metric's units: `points` for a share, because 0.012 is 1.2 percentage points, and `units` for every other kind.
 */
export type ChangeUnit = 'relative' | 'points' | 'units'

export function changeUnitOf(differenceType: ExperimentDifferenceType, kind: MetricKind): ChangeUnit {
    if (differenceType === 'relative') {
        return 'relative'
    }
    return kind === 'rate' ? 'points' : 'units'
}

export function formatChangeSize(change: number, unit: ChangeUnit): string {
    const magnitude = Math.abs(change)
    switch (unit) {
        case 'relative':
            return `${(magnitude * 100).toFixed(1)}%`
        case 'points':
            return `${(magnitude * 100).toFixed(1)} pts`
        case 'units':
            return formatDecimal(magnitude, magnitude >= 1000 ? 0 : magnitude >= 100 ? 1 : 2)
    }
}

/** A signed change: `+12.4%`, `−1.2 pts`, `+3.50`. A change that rounds to zero has no sign. */
export function formatDelta(change: number, unit: ChangeUnit): string {
    const size = formatChangeSize(change, unit)
    if (size === formatChangeSize(0, unit)) {
        return size
    }
    return `${change > 0 ? '+' : MINUS}${size}`
}

/** The web's `formatChanceToWin`. */
export function formatChance(fraction: number): string {
    const percent = fraction * 100
    if (percent >= 99.9) {
        return '> 99.9%'
    }
    if (percent <= 0.1) {
        return '< 0.1%'
    }
    return percent < 1 ? `${percent.toFixed(2)}%` : `${percent.toFixed(1)}%`
}

/** The web's `formatPValue`. */
export function formatPValue(p: number): string {
    if (p < 0.001) {
        return '< 0.001'
    }
    return p < 0.01 ? p.toFixed(4) : p.toFixed(3)
}

/** A level such as 0.95 as `95%`, keeping one decimal for levels like 0.975. */
export function formatLevel(level: number): string {
    const percent = Math.round(level * 1000) / 10
    return Number.isInteger(percent) ? `${percent}%` : `${percent.toFixed(1)}%`
}

/** A significance cut-off such as 0.05, without trailing zeros. */
export function formatAlpha(alpha: number): string {
    return String(Math.round(alpha * 10000) / 10000)
}

export function formatCountdown(ms: number): string {
    const seconds = Math.max(0, Math.ceil(ms / 1000))
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function plural(count: number, one: string, many: string): string {
    return count === 1 ? one : many
}

/** `just now`, `12 min ago`, `5 h ago`, `3 d ago`. */
export function formatAge(ms: number): string {
    if (ms < MINUTE_MS) {
        return 'just now'
    }
    if (ms < HOUR_MS) {
        return `${Math.floor(ms / MINUTE_MS)} min ago`
    }
    if (ms < DAY_MS) {
        return `${Math.floor(ms / HOUR_MS)} h ago`
    }
    return `${Math.floor(ms / DAY_MS)} d ago`
}

/** `02:00` today, `Nov 3, 02:00` on another day. */
export function formatStamp(at: Date, now: Date, clock24?: boolean): string {
    const time = formatClock(at, clock24)
    return calendarDaysBetween(at, now) === 0 ? time : `${formatMonthDay(at)}, ${time}`
}

function parseTime(value: string | null | undefined): number | null {
    const parsed = value ? Date.parse(value) : Number.NaN
    return Number.isNaN(parsed) ? null : parsed
}

// ---------- Statistics settings ----------

export interface StatsSettings {
    method: ExperimentMethod
    /** The interval level, such as 0.95. For a Frequentist analysis it is 1 − alpha. */
    level: number
    /** The Frequentist significance cut-off, such as 0.05. */
    alpha: number
}

const DEFAULT_LEVEL = 0.95

function fractionIn(value: unknown): number | null {
    return typeof value === 'number' && value > 0 && value < 1 ? value : null
}

/** `stats_config` with the server's defaults: Bayesian `ci_level` 0.95, Frequentist `alpha` 0.05. */
export function statsSettingsOf(experiment: ExperimentApi, latest?: ExperimentResultsRunApi | null): StatsSettings {
    const method = methodOf(experiment, latest)
    const config = isRecord(experiment.stats_config) ? experiment.stats_config : {}
    if (method === 'freq') {
        const frequentist = isRecord(config.frequentist) ? config.frequentist : {}
        const alpha = fractionIn(frequentist.alpha) ?? 1 - DEFAULT_LEVEL
        return { method, level: 1 - alpha, alpha }
    }
    const bayesian = isRecord(config.bayesian) ? config.bayesian : {}
    const level = fractionIn(bayesian.ci_level) ?? DEFAULT_LEVEL
    return { method, level, alpha: 1 - level }
}

export function methodLabel(settings: StatsSettings): string {
    return `${settings.method === 'freq' ? 'Frequentist' : 'Bayesian'}, ${formatLevel(settings.level)}`
}

// ---------- Metrics ----------

/** How a metric's value reads: a share of people, an average per person, a ratio or a quantile. */
export type MetricKind = 'rate' | 'mean' | 'ratio' | 'quantile'

export interface MetricDef extends ResultMetric {
    role: 'primary' | 'secondary'
    kind: MetricKind
    /** The `metric_type` of a share: what "did it" means in a sentence. */
    rateVerb: string
    /** For a quantile metric, such as 0.9. */
    quantile: number | null
}

type RawMetric = Record<string, unknown>

function nodeName(node: unknown): string | null {
    if (!isRecord(node)) {
        return null
    }
    for (const key of ['custom_name', 'name', 'event', 'table_name']) {
        const value = node[key]
        if (typeof value === 'string' && value.trim()) {
            return value.trim()
        }
    }
    return null
}

/** The web's `getDefaultMetricTitle`, for a metric saved without a name. */
function defaultTitle(metric: RawMetric): string {
    switch (metric.metric_type) {
        case 'mean':
            return nodeName(metric.source) ?? 'Untitled metric'
        case 'funnel': {
            const series = Array.isArray(metric.series) ? metric.series : []
            return nodeName(series[0]) ?? 'Untitled funnel'
        }
        case 'ratio':
            return `${nodeName(metric.numerator) ?? 'Numerator'} / ${nodeName(metric.denominator) ?? 'Denominator'}`
        case 'retention':
            return `${nodeName(metric.start_event) ?? 'Start event'} / ${nodeName(metric.completion_event) ?? 'Completion event'}`
        case 'quantile': {
            const quantile = typeof metric.quantile === 'number' ? metric.quantile : null
            const source = nodeName(metric.source) ?? 'Untitled metric'
            return quantile === null ? source : `p${Math.round(quantile * 100)} ${source}`
        }
        default:
            return 'Untitled metric'
    }
}

/** The web's `isProportionMetric`: funnels, retention and a mean with a threshold read as a share of people. */
function kindOf(metric: RawMetric): MetricKind {
    switch (metric.metric_type) {
        case 'funnel':
        case 'retention':
            return 'rate'
        case 'ratio':
            return 'ratio'
        case 'quantile':
            return 'quantile'
        default:
            return typeof metric.threshold === 'number' ? 'rate' : 'mean'
    }
}

function rateVerbOf(metric: RawMetric): string {
    switch (metric.metric_type) {
        case 'retention':
            return 'came back'
        case 'mean':
            return 'reached the threshold'
        default:
            return 'converted'
    }
}

function defOf({ raw, savedName, metric }: MetricEntry, role: MetricRole): MetricDef {
    const ownName = typeof raw.name === 'string' && raw.name.trim() ? raw.name.trim() : null
    return {
        ...metric,
        // The list's names, with the web's default title instead of a generic one for an unnamed metric.
        name: savedName ?? ownName ?? defaultTitle(raw),
        role,
        kind: kindOf(raw),
        rateVerb: rateVerbOf(raw),
        quantile: typeof raw.quantile === 'number' ? raw.quantile : null,
    }
}

/**
 * The metrics of each role in the list's `orderedMetricsOf` order, which follows the web, so the first card is the
 * metric the list's headline and the finish sheet's suggestion read. The detail adds the kind and a readable name.
 */
export function metricDefsOf(experiment: ExperimentApi): { primary: MetricDef[]; secondary: MetricDef[] } {
    return {
        primary: orderedMetricsOf(experiment, 'primary').map((entry) => defOf(entry, 'primary')),
        secondary: orderedMetricsOf(experiment, 'secondary').map((entry) => defOf(entry, 'secondary')),
    }
}

export function formatMetricValue(kind: MetricKind, value: number | null): string {
    if (value === null || !Number.isFinite(value)) {
        return '—'
    }
    if (kind === 'rate') {
        return `${(value * 100).toFixed(2)}%`
    }
    const magnitude = Math.abs(value)
    return formatDecimal(value, magnitude >= 1000 ? 0 : magnitude >= 100 ? 1 : 2)
}

/** What one number in a metric reads as: `checkout` is the metric name, so the label stays generic. */
export function valueNoun(def: MetricDef): string {
    switch (def.kind) {
        case 'rate':
            return def.metricType === 'retention'
                ? 'retention rate'
                : def.metricType === 'mean'
                  ? 'share'
                  : 'conversion rate'
        case 'ratio':
            return 'ratio'
        case 'quantile':
            return def.quantile === null ? 'value' : `p${Math.round(def.quantile * 100)}`
        default:
            return 'average'
    }
}

export type IntervalSide = 'good' | 'bad' | 'none'

export interface CellModel {
    key: string
    /** The variant's position in the flag's variants, for its color. */
    colorIndex: number
    isBaseline: boolean
    samples: number
    value: number | null
    /** People who did it, for a share. */
    numerator: number | null
    delta: number | null
    interval: [number, number] | null
    /** Goal-adjusted. */
    chanceToWin: number | null
    pValue: number | null
    significant: boolean
    better: boolean | null
    /** Where the whole interval sits against 0, judged by the goal. */
    side: IntervalSide
}

export type MetricCardState = 'ready' | 'pending' | 'failed' | 'not_enough' | 'none'

export interface MetricCardModel {
    def: MetricDef
    state: MetricCardState
    baseline: CellModel | null
    variants: CellModel[]
    leaderKey: string | null
    unit: ChangeUnit
    /** Half the width of the interval axis, in the card's unit: every bar on the card shares it. */
    scale: number
    error: string | null
}

function sideOf(interval: [number, number], goal: MetricGoal): IntervalSide {
    const [low, high] = interval
    if (low <= 0 && high >= 0) {
        return 'none'
    }
    const up = low > 0
    return (goal === 'decrease' ? !up : up) ? 'good' : 'bad'
}

function colorIndexOf(order: readonly string[], key: string): number {
    const index = order.indexOf(key)
    return index === -1 ? order.length : index
}

/** One axis per card: the widest interval end, rounded up to a 5% step, never under 5%. */
export function intervalScale(intervals: readonly [number, number][]): number {
    const widest = intervals.reduce((max, [low, high]) => Math.max(max, Math.abs(low), Math.abs(high)), 0.05)
    return Math.ceil((widest * 100) / 5) * 0.05
}

export function metricCardOf(
    def: MetricDef,
    latest: ExperimentResultsRunApi | null | undefined,
    variantOrder: readonly string[],
    differenceType: ExperimentDifferenceType
): MetricCardModel {
    const empty: MetricCardModel = {
        def,
        state: 'none',
        baseline: null,
        variants: [],
        leaderKey: null,
        unit: changeUnitOf(differenceType, def.kind),
        scale: 0.05,
        error: null,
    }
    const row = latest && def.uuid ? latest.results.find((candidate) => candidate.metric_uuid === def.uuid) : undefined
    if (!row) {
        return empty
    }
    if (row.status === 'pending') {
        return { ...empty, state: 'pending' }
    }
    if (row.status === 'failed') {
        return { ...empty, state: 'failed', error: row.error_message ?? null }
    }
    const raw = metricResultOf(latest, def)
    const result = resultOf(def, raw, differenceType)
    if (!result || !raw?.baseline) {
        return { ...empty, state: 'not_enough' }
    }
    const rate = def.kind === 'rate'
    const baselineSum = raw.baseline.sum
    const baseline: CellModel = {
        key: result.baseline.key,
        colorIndex: colorIndexOf(variantOrder, result.baseline.key),
        isBaseline: true,
        samples: result.baseline.samples,
        value: result.baseline.value,
        numerator: rate ? baselineSum : null,
        delta: null,
        interval: null,
        chanceToWin: null,
        pValue: null,
        significant: false,
        better: null,
        side: 'none',
    }
    const sums = new Map((raw.variant_results ?? []).map((variant) => [variant.key, variant.sum]))
    const variants = result.variants
        .map(
            (variant): CellModel => ({
                key: variant.key,
                colorIndex: colorIndexOf(variantOrder, variant.key),
                isBaseline: false,
                samples: variant.samples,
                value: variant.value,
                numerator: rate ? (sums.get(variant.key) ?? null) : null,
                delta: variant.delta,
                interval: variant.interval,
                chanceToWin: variant.chanceToWin ?? null,
                pValue: variant.pValue ?? null,
                significant: variant.significant,
                better: variant.better,
                side: sideOf(variant.interval, def.goal),
            })
        )
        .sort((a, b) => a.colorIndex - b.colorIndex)
    return {
        def,
        state: 'ready',
        baseline,
        variants,
        leaderKey: leaderOf(result)?.key ?? null,
        unit: empty.unit,
        scale: intervalScale(variants.flatMap((variant) => (variant.interval ? [variant.interval] : []))),
        error: null,
    }
}

/** A point on the interval axis, from 0 (left) to 1 (right). */
export function axisPosition(fraction: number, scale: number): number {
    return Math.min(1, Math.max(0, (fraction + scale) / (2 * scale)))
}

// ---------- Header ----------

export interface Byline {
    timing: string
    flag: string
}

function personName(user: ExperimentApi['created_by'] | null | undefined): string | null {
    if (!user) {
        return null
    }
    const name = [user.first_name, user.last_name].filter(Boolean).join(' ').trim()
    return name || user.email || null
}

export function isWatching(experiment: ExperimentApi, status: ExperimentStatus, now: number): boolean {
    const start = parseTime(experiment.start_date)
    return status === 'running' && start !== null && now - start >= 0 && now - start < WATCH_WINDOW_MS
}

function launchedPhrase(start: Date, now: Date, clock24?: boolean): string {
    const ago = now.getTime() - start.getTime()
    const when =
        ago < MINUTE_MS
            ? 'just now'
            : ago < HOUR_MS
              ? `${Math.floor(ago / MINUTE_MS)} min ago`
              : `${Math.floor(ago / HOUR_MS)} h ago`
    const days = calendarDaysBetween(start, now)
    const day = days === 0 ? 'today' : days === 1 ? 'yesterday' : formatMonthDay(start)
    return `Launched ${when} · ${day} ${formatClock(start, clock24)}`
}

export function bylineOf(
    experiment: ExperimentApi,
    status: ExperimentStatus,
    settings: StatsSettings,
    options: { now: Date; viewerUuid: string | null; clock24?: boolean }
): Byline {
    const { now, viewerUuid, clock24 } = options
    const start = parseTime(experiment.start_date)
    const end = parseTime(experiment.end_date)
    let timing: string
    if (status === 'draft' || start === null) {
        const created = parseTime(experiment.created_at)
        const by = viewerUuid && experiment.created_by?.uuid === viewerUuid ? 'you' : personName(experiment.created_by)
        timing = [
            'Draft',
            created === null ? null : `created ${formatMonthDay(new Date(created))}${by ? ` by ${by}` : ''}`,
        ]
            .filter(Boolean)
            .join(' · ')
    } else if (status === 'complete' && end !== null) {
        const days = Math.max(0, Math.floor((end - start) / DAY_MS))
        timing = `Ran ${days} ${plural(days, 'day', 'days')} · ${formatMonthDay(new Date(start))} to ${formatMonthDay(new Date(end))}`
    } else if (status === 'paused') {
        // The API has no pause time, so the line says when it started instead of how long it ran.
        const days = Math.floor((now.getTime() - start) / DAY_MS)
        const ago = days === 0 ? 'today' : `${days} ${plural(days, 'day', 'days')} ago`
        timing = `Paused · started ${formatMonthDay(new Date(start))}, ${ago}`
    } else if (now.getTime() - start < DAY_MS) {
        timing = launchedPhrase(new Date(start), now, clock24)
    } else {
        const days = Math.floor((now.getTime() - start) / DAY_MS)
        timing = `Running ${days} ${plural(days, 'day', 'days')} · started ${formatMonthDay(new Date(start))}`
    }
    return { timing, flag: `${experiment.feature_flag_key} · ${methodLabel(settings)}` }
}

// ---------- Status card ----------

export type RefreshPhase =
    | { kind: 'idle' }
    | { kind: 'pulling' }
    | { kind: 'recalculating'; done: number; total: number }
    | { kind: 'window'; retryAt: number }
    | { kind: 'stuck' }

export type StatusTone = 'fresh' | 'aging' | 'stale' | 'neutral' | 'info' | 'final'

export interface StatusCardModel {
    tone: StatusTone
    spinner: boolean
    strong: string | null
    text: string
    sub: string | null
    /** 0 to 1 while a recalculation runs. */
    progress: number | null
}

export interface StatusCardInput {
    status: ExperimentStatus
    /** Undefined while loading, null when the experiment has no stored results. */
    latest: ExperimentResultsRunApi | null | undefined
    latestFailed: boolean
    phase: RefreshPhase
    /** The stored results come from a run this device started. */
    mine: boolean
    now: number
    clock24?: boolean
}

function sourceLabel(source: ReturnType<typeof freshnessOf>['source'], mine: boolean): string | null {
    if (mine) {
        return 'your refresh'
    }
    switch (source) {
        case 'daily':
        case 'fallback':
            return 'daily run'
        case 'manual':
            return 'manual refresh'
        default:
            return null
    }
}

function ageTone(ageMs: number): StatusTone {
    return ageMs >= STALE_MS ? 'stale' : ageMs >= AGING_MS ? 'aging' : 'fresh'
}

/** The quiet card under the hypothesis: which run the numbers come from, how old they are, and a refresh's progress. */
export function statusCardOf(input: StatusCardInput): StatusCardModel | null {
    const { status, latest, latestFailed, phase, mine, now, clock24 } = input
    if (status === 'draft') {
        return null
    }
    const base: StatusCardModel = { tone: 'neutral', spinner: false, strong: null, text: '', sub: null, progress: null }
    const freshness = freshnessOf(latest, now)
    const stamp = freshness.resultsAt ? formatStamp(freshness.resultsAt, new Date(now), clock24) : null
    if (phase.kind === 'recalculating') {
        const total = Math.max(phase.total, 0)
        return {
            ...base,
            spinner: true,
            strong: 'Recalculating',
            text: total > 0 ? `${Math.min(phase.done, total)} of ${total} metrics done` : 'starting',
            progress: total > 0 ? Math.max(0.06, Math.min(1, phase.done / total)) : 0.06,
        }
    }
    if (phase.kind === 'pulling') {
        return { ...base, text: 'Updating…' }
    }
    if (phase.kind === 'window') {
        return {
            ...base,
            tone: 'fresh',
            text: `Updated just now · refresh again in ${formatCountdown(phase.retryAt - now)}`,
        }
    }
    if (phase.kind === 'stuck') {
        return {
            ...base,
            tone: 'aging',
            strong: 'Still working',
            text: 'pull again to check',
            sub: stamp ? `The results from ${stamp} stay until it is done.` : 'The last results stay until it is done.',
        }
    }
    if (latest === undefined) {
        return latestFailed
            ? { ...base, tone: 'stale', text: "Couldn't load the results · pull down to try again" }
            : { ...base, text: 'Loading the results…' }
    }
    if (latest === null) {
        if (status === 'complete') {
            return { ...base, text: 'No stored results for this experiment' }
        }
        return { ...base, tone: 'info', text: 'No results yet · pull down to calculate them' }
    }
    if (status === 'complete') {
        return {
            ...base,
            tone: 'final',
            strong: 'Final results',
            text: freshness.resultsAt
                ? `from the ${formatMonthDay(freshness.resultsAt)}, ${formatClock(freshness.resultsAt, clock24)} run`
                : 'from the last run',
        }
    }
    const ageMs = freshness.ageMs ?? 0
    const parts = [
        stamp ? `Results from ${stamp}` : 'Stored results',
        freshness.ageMs === null ? null : formatAge(ageMs),
        sourceLabel(freshness.source, mine),
    ].filter((part): part is string => Boolean(part))
    return {
        ...base,
        tone: freshness.ageMs === null ? 'neutral' : ageTone(ageMs),
        text: parts.join(' · '),
        sub: latest.exceeds_recalculation_age_limit
            ? 'This experiment started too long ago to recalculate. A pull reloads these results.'
            : null,
    }
}

// ---------- Progress ----------

export interface ProgressModel {
    current: number
    recommended: number | null
    state: 'early' | 'reached' | 'to_go'
    daysToGo: number | null
    perDay: number | null
    daysRunning: number | null
    /** The relative change the target is sized to detect, as a percentage. */
    minimumEffect: number | null
    /** How full the bar is, 0 to 1. */
    fill: number
}

export function progressOf(
    target: ExperimentRunningTimeTargetApi | undefined,
    fallbackCurrent: number | null
): ProgressModel | null {
    if (!target) {
        return null
    }
    const current = target.current_sample_size ?? fallbackCurrent ?? 0
    const recommended =
        target.recommended_sample_size && target.recommended_sample_size > 0 ? target.recommended_sample_size : null
    const perDay = target.outlook && target.outlook.exposures_per_day > 0 ? target.outlook.exposures_per_day : null
    const daysRunning = target.outlook ? Math.floor(target.outlook.days_since_launch) : null
    const minimumEffect = Number.isFinite(target.minimum_detectable_effect) ? target.minimum_detectable_effect : null
    // No outlook outside manual mode means the results cover too little time to size anything yet.
    const tooEarly = target.outlook === null && target.current_sample_size !== null
    if (recommended === null || (tooEarly && current < recommended)) {
        const fill = recommended === null ? 0.015 : Math.max(0.015, current / recommended)
        return { current, recommended, state: 'early', daysToGo: null, perDay, daysRunning, minimumEffect, fill }
    }
    if (current >= recommended) {
        return { current, recommended, state: 'reached', daysToGo: 0, perDay, daysRunning, minimumEffect, fill: 1 }
    }
    return {
        current,
        recommended,
        state: 'to_go',
        daysToGo: perDay ? Math.ceil((recommended - current) / perDay) : null,
        perDay,
        daysRunning,
        minimumEffect,
        fill: Math.max(0.015, current / recommended),
    }
}

export function progressLabel(progress: ProgressModel): string {
    switch (progress.state) {
        case 'reached':
            return 'Target reached'
        case 'early':
            return 'Too early to tell'
        default:
            return progress.daysToGo === null
                ? `${formatCount((progress.recommended ?? 0) - progress.current)} to go`
                : `~${progress.daysToGo} ${plural(progress.daysToGo, 'day', 'days')} to go`
    }
}

// ---------- Exposures ----------

/** The exposure query's key for people who saw more than one variant. */
export const MULTIPLE_VARIANTS_KEY = '$multiple'

/**
 * The web's `getTotalExposures`: the people of every variant in the exposure answer's timeseries, `$multiple` included.
 * The Exposures header, the Watching card and the progress fallback all read this one number.
 */
export function exposureTotalOf(response: ExperimentExposureResponseApi | undefined): number | null {
    if (!response) {
        return null
    }
    return (response.timeseries ?? []).reduce(
        (total, series) => total + Number(response.total_exposures?.[series.variant] || 0),
        0
    )
}

export interface ExposureRow {
    key: string
    colorIndex: number
    count: number
    /** Share of the variants' exposures, 0 to 1. */
    share: number
}

export interface SampleRatioWarning {
    keys: string[]
    actual: number[]
    expected: number[]
    pValue: number
}

export interface ExposureModel {
    total: number
    rows: ExposureRow[]
    multiple: number
    srm: SampleRatioWarning | null
}

function splitChecksSkipped(response: ExperimentExposureResponseApi): boolean {
    const checks = isRecord(response) && Array.isArray(response.health_checks) ? response.health_checks : []
    return checks.some((check) => isRecord(check) && check.key === 'srm' && check.status === 'not_applicable')
}

export function exposureModelOf(
    response: ExperimentExposureResponseApi | undefined,
    variantOrder: readonly string[]
): ExposureModel | null {
    if (!response) {
        return null
    }
    const totals = response.total_exposures ?? {}
    const keys = [
        ...variantOrder,
        ...Object.keys(totals).filter((key) => key !== MULTIPLE_VARIANTS_KEY && !variantOrder.includes(key)),
    ]
    const counts = keys.map((key) => Number(totals[key] ?? 0))
    const variantsTotal = counts.reduce((sum, count) => sum + count, 0)
    const multiple = Number(totals[MULTIPLE_VARIANTS_KEY] ?? 0)
    const rows = keys.map((key, index) => ({
        key,
        colorIndex: index,
        count: counts[index] ?? 0,
        share: variantsTotal > 0 ? (counts[index] ?? 0) / variantsTotal : 0,
    }))
    const mismatch = response.sample_ratio_mismatch
    let srm: SampleRatioWarning | null = null
    if (mismatch && mismatch.p_value < SAMPLE_RATIO_P_VALUE && !splitChecksSkipped(response)) {
        // `expected` holds expected counts; normalizing also reads a payload of shares correctly.
        const tested = keys.filter((key) => typeof mismatch.expected[key] === 'number')
        const expectedTotal = tested.reduce((sum, key) => sum + (mismatch.expected[key] ?? 0), 0)
        const actualTotal = tested.reduce((sum, key) => sum + Number(totals[key] ?? 0), 0)
        if (tested.length >= 2 && expectedTotal > 0 && actualTotal > 0) {
            srm = {
                keys: tested,
                actual: tested.map((key) => Number(totals[key] ?? 0) / actualTotal),
                expected: tested.map((key) => (mismatch.expected[key] ?? 0) / expectedTotal),
                pValue: mismatch.p_value,
            }
        }
    }
    return { total: exposureTotalOf(response) ?? 0, rows, multiple, srm }
}

function wholePercents(shares: readonly number[]): string {
    return shares.map((share) => String(Math.round(share * 100))).join(`${NBSP}/${NBSP}`)
}

export function sampleRatioText(warning: SampleRatioWarning): { strong: string; text: string } {
    const expected = wholePercents(warning.expected)
    const p = warning.pValue < 0.001 ? 'p < 0.001' : `p = ${formatPValue(warning.pValue)}`
    const [first, second] = warning.keys
    const actual =
        warning.keys.length === 2 && first && second
            ? `${first} has ${Math.round((warning.actual[0] ?? 0) * 100)}% and ${second} has ${Math.round((warning.actual[1] ?? 0) * 100)}%`
            : `The split came out ${wholePercents(warning.actual)}`
    return {
        strong: 'Uneven split.',
        text: `${actual}, but the flag splits ${expected} (${p}). Results may be biased.`,
    }
}

// ---------- Health ----------

export interface HealthItem {
    key: string
    severity: 'critical' | 'warning' | 'info'
    title: string
    detail: string
}

const SEVERITY_RANK: Record<HealthItem['severity'], number> = { critical: 0, warning: 1, info: 2 }

function severityOf(value: unknown): HealthItem['severity'] {
    return value === 'critical' || value === 'warning' ? value : 'info'
}

/**
 * The health findings and the exposure query's own findings, most severe first. The exposures card shows the sample
 * ratio test, so its finding is left out here.
 */
export function healthItemsOf(
    health: ExperimentHealthApi | undefined,
    exposures: ExperimentExposureResponseApi | undefined
): HealthItem[] {
    const items: HealthItem[] = []
    const seen = new Set<string>()
    const add = (code: string, severity: unknown, title: string | undefined, detail: string): void => {
        const heading = title?.trim() || detail
        const key = `${code}|${heading}`
        if (seen.has(key) || code === 'srm') {
            return
        }
        seen.add(key)
        items.push({ key, severity: severityOf(severity), title: heading, detail: title?.trim() ? detail : '' })
    }
    for (const finding of health?.findings ?? []) {
        add(finding.code, finding.severity, finding.title, finding.detail)
    }
    for (const finding of exposures?.health_findings ?? []) {
        add(finding.code, finding.severity, finding.title, finding.detail)
    }
    return items.sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])
}

// ---------- Flag ----------

interface FlagGroup {
    rollout_percentage?: number | null
    properties?: unknown[]
}

function flagFilters(experiment: ExperimentApi): Record<string, unknown> {
    return isRecord(experiment.feature_flag?.filters) ? experiment.feature_flag.filters : {}
}

function flagGroups(experiment: ExperimentApi): FlagGroup[] {
    const groups = flagFilters(experiment).groups
    return Array.isArray(groups) ? groups.filter(isRecord) : []
}

/** The flag's split as `50 / 50`, in the flag's variant order. */
export function splitOf(experiment: ExperimentApi): string | null {
    const multivariate = flagFilters(experiment).multivariate
    const variants = isRecord(multivariate) && Array.isArray(multivariate.variants) ? multivariate.variants : []
    const shares = variants.flatMap((variant) =>
        isRecord(variant) && typeof variant.rollout_percentage === 'number' ? [variant.rollout_percentage] : []
    )
    return shares.length ? shares.map((share) => String(Math.round(share))).join(`${NBSP}/${NBSP}`) : null
}

function rolloutPercent(experiment: ExperimentApi): number | null {
    const percents = flagGroups(experiment).map((group) =>
        typeof group.rollout_percentage === 'number' ? group.rollout_percentage : 100
    )
    if (!percents.length) {
        return null
    }
    const first = percents[0] ?? 100
    return percents.every((percent) => percent === first) ? first : null
}

export interface RolloutModel {
    flagKey: string
    flagId: number | null
    line: string
}

export function rolloutOf(experiment: ExperimentApi, status: ExperimentStatus): RolloutModel {
    const split = splitOf(experiment)
    const splitText = split ? `split ${split}` : null
    const shipped = shippedVariantOf(experiment)
    let line: string
    if (status === 'draft') {
        line = ['Off until launch', splitText].filter(Boolean).join(' · ')
    } else if (shipped) {
        line = status === 'complete' ? `${shipped} at 100%` : `${shipped} at 100% · set on the flag`
    } else if (status === 'complete') {
        line = split ? `Still splitting ${split}` : 'Flag unchanged'
    } else if (status === 'paused') {
        line = ['Flag off', splitText].filter(Boolean).join(' · ')
    } else if (status === 'frozen') {
        line = ['Exposure frozen', splitText].filter(Boolean).join(' · ')
    } else {
        const rollout = rolloutPercent(experiment)
        line = [rollout === null ? 'Rollout varies' : `Rollout ${Math.round(rollout)}%`, splitText]
            .filter(Boolean)
            .join(' · ')
    }
    const flagId = experiment.feature_flag?.id
    return { flagKey: experiment.feature_flag_key, flagId: typeof flagId === 'number' ? flagId : null, line }
}

// ---------- Draft ----------

export interface DraftVariant {
    key: string
    colorIndex: number
    note: string | null
    percent: number | null
}

export function draftVariantsOf(experiment: ExperimentApi): DraftVariant[] {
    const multivariate = flagFilters(experiment).multivariate
    const variants = isRecord(multivariate) && Array.isArray(multivariate.variants) ? multivariate.variants : []
    const notes = isRecord(experiment.parameters?.variant_notes) ? experiment.parameters.variant_notes : {}
    return variants.filter(isRecord).flatMap((variant, index): DraftVariant[] => {
        if (typeof variant.key !== 'string') {
            return []
        }
        const note = notes[variant.key]
        return [
            {
                key: variant.key,
                colorIndex: index,
                note: typeof note === 'string' && note.trim() ? note.trim() : null,
                percent: typeof variant.rollout_percentage === 'number' ? variant.rollout_percentage : null,
            },
        ]
    })
}

/** Who joins at launch, from the flag's release conditions. Property names stay on the web. */
export function audienceOf(experiment: ExperimentApi): string {
    const groups = flagGroups(experiment)
    if (groups.length === 0) {
        return 'Everyone who evaluates the flag'
    }
    if (groups.length > 1) {
        return `${groups.length} release conditions`
    }
    const group = groups[0] ?? {}
    const percent = typeof group.rollout_percentage === 'number' ? Math.round(group.rollout_percentage) : 100
    const filters = Array.isArray(group.properties) ? group.properties.length : 0
    return filters === 0
        ? `${percent}% of all users`
        : `${percent}% of users who match ${filters} ${plural(filters, 'filter', 'filters')}`
}

// ---------- Complete ----------

export interface ConclusionModel {
    conclusion: NonNullable<ExperimentApi['conclusion']> | null
    ended: string | null
    shipped: string | null
    line: string
    comment: string | null
}

export function conclusionOf(experiment: ExperimentApi): ConclusionModel {
    const end = parseTime(experiment.end_date)
    const shipped = shippedVariantOf(experiment)
    const split = splitOf(experiment)
    // `ship_variant` with `release_to_everyone` puts a 100% condition without filters first.
    const [first] = flagGroups(experiment)
    const everyone =
        first !== undefined &&
        (!Array.isArray(first.properties) || first.properties.length === 0) &&
        (first.rollout_percentage ?? 100) === 100
    let line: string
    if (shipped) {
        line = `Shipped ${shipped} to ${everyone ? 'all users' : 'the experiment population'}.`
    } else {
        line = split ? `Nothing shipped. The flag still splits people ${split}.` : 'Nothing shipped.'
    }
    return {
        conclusion: experiment.conclusion ?? null,
        ended: end === null ? null : formatMonthDay(new Date(end)),
        shipped,
        line,
        comment: experiment.conclusion_comment?.trim() || null,
    }
}
