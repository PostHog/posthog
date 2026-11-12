import type {
    ExperimentApi,
    ExperimentConclusionApi,
    ExperimentListItemApi,
    ExperimentQueryResultApi,
    ExperimentResultsRunApi,
    ExperimentStatsApi,
    ExperimentVariantResultApi,
} from '@/api/experiments'
import { isRecord } from '@/lib/records'

// Pure reads of the experiments API shapes. Relative changes are fractions: 0.124 is +12.4%. The web's
// `MetricsView/shared/utils.ts` is the reference: the change is the midpoint of the interval, and a `decrease` goal
// turns "better" and the chance to win around.

const HOUR_MS = 60 * 60_000
const DAY_MS = 24 * HOUR_MS

/** A launch this recent shows the New badge in the list. */
export const NEW_LAUNCH_MS = DAY_MS
/** A Bayesian leader at or above this chance to win reads as "leading" in a row. */
export const LEADING_CHANCE = 0.8
/** A Frequentist leader under this p-value reads as "leading" in a row. */
export const LEADING_P_VALUE = 0.1

export type ExperimentStatus = 'draft' | 'running' | 'paused' | 'frozen' | 'complete'
export type ExperimentMethod = 'bayes' | 'freq'
export type ExperimentDifferenceType = 'relative' | 'absolute'
export type ExperimentConclusion = ExperimentConclusionApi
export type MetricGoal = 'increase' | 'decrease'

export interface HeadlineResult {
    /**
     * `significant`: a variant differs from control. `leading`: a variant is ahead but not significant. `target`: the
     * sample target is reached with no significant result. `needs_data`: too early to say. `not_yet`: no stored
     * results yet.
     */
    kind: 'significant' | 'leading' | 'not_yet' | 'needs_data' | 'target'
    leader?: string
    method?: ExperimentMethod
    /** Change against control, as a fraction for relative differences or metric units for absolute differences. */
    delta?: number
    differenceType?: ExperimentDifferenceType
    /** True when the leader's change is in the metric's good direction. */
    better?: boolean
    /** Goal-adjusted, as a fraction. Bayesian only. */
    chanceToWin?: number
    /** Frequentist only. */
    pValue?: number
    /** People exposed across the variants of the primary metric's result. */
    exposures?: number
    /** ISO time the results cover data up to. */
    resultsAt?: string
}

export type RowHeadline = HeadlineResult | 'loading' | 'none' | 'error'

export interface ExperimentRow {
    id: string
    name: string
    flagKey: string
    status: ExperimentStatus
    method: ExperimentMethod
    variants: string[]
    startedAt: string | null
    endedAt: string | null
    createdAt: string
    /** Whole days from launch to the end, or to now while running. Null before launch. */
    days: number | null
    conclusion: ExperimentConclusion | null
    /** The variant the flag serves to everyone, read from the flag's split. */
    shippedVariant: string | null
    /** The headline changed since the last look on this device. */
    changed: boolean
    headline: RowHeadline
    createdBy: { uuid: string; name: string; email: string } | null
    /** Launched within `NEW_LAUNCH_MS`. */
    isNew: boolean
    /** The saved running-time estimate's sample size, from the list. A row's "days to target" reads it. */
    targetSampleSize: number | null
}

export interface ResultMetric {
    uuid: string | null
    name: string
    goal: MetricGoal
    metricType: string
}

export interface VariantResult {
    key: string
    samples: number
    /** The metric's value for this variant, as the web shows it before formatting. Null when it cannot be read. */
    value: number | null
    /** Change against control, in the units named by differenceType. */
    delta: number
    differenceType: ExperimentDifferenceType
    interval: [number, number]
    /** Goal-adjusted chance to win, as a fraction. Bayesian only. */
    chanceToWin?: number
    pValue?: number
    significant: boolean
    /** The change is in the metric's good direction. */
    better: boolean
}

export interface BaselineResult {
    key: string
    samples: number
    value: number | null
}

export interface PrimaryResult {
    metric: ResultMetric
    baseline: BaselineResult
    variants: VariantResult[]
}

export function experimentStatusOf(experiment: ExperimentListItemApi | ExperimentApi): ExperimentStatus {
    switch (experiment.status) {
        case 'draft':
            return 'draft'
        case 'running':
            return 'running'
        case 'paused':
            return 'paused'
        case 'exposure_frozen':
            return 'frozen'
        case 'stopped':
            return 'complete'
    }
    // Older payloads have no status: derive it the way `ExperimentQueryStatus` does.
    if (!experiment.start_date) {
        return 'draft'
    }
    if (experiment.end_date) {
        return 'complete'
    }
    return experiment.feature_flag?.active === false ? 'paused' : 'running'
}

/** Running, paused and frozen experiments are live: they still collect exposures or can again. */
export function isLiveStatus(status: ExperimentStatus): boolean {
    return status === 'running' || status === 'paused' || status === 'frozen'
}

interface FlagVariantShape {
    key: string
    rollout_percentage?: number
}

function flagVariants(experiment: ExperimentListItemApi | ExperimentApi): FlagVariantShape[] {
    const filters = experiment.feature_flag?.filters
    const multivariate = isRecord(filters) ? filters.multivariate : undefined
    const variants = isRecord(multivariate) ? multivariate.variants : undefined
    if (!Array.isArray(variants)) {
        return []
    }
    return variants.filter(
        (variant): variant is FlagVariantShape => isRecord(variant) && typeof variant.key === 'string'
    )
}

export function variantKeysOf(experiment: ExperimentListItemApi | ExperimentApi): string[] {
    return flagVariants(experiment).map((variant) => variant.key)
}

/** The variant that holds 100% of the split after a ship, or null. */
export function shippedVariantOf(experiment: ExperimentListItemApi | ExperimentApi): string | null {
    const variants = flagVariants(experiment)
    if (variants.length < 2) {
        return null
    }
    return variants.find((variant) => variant.rollout_percentage === 100)?.key ?? null
}

export function methodOf(
    experiment: ExperimentApi | ExperimentListItemApi,
    latest?: ExperimentResultsRunApi | null
): ExperimentMethod {
    const config = 'stats_config' in experiment ? experiment.stats_config : undefined
    if (isRecord(config) && typeof config.method === 'string') {
        return config.method === 'frequentist' ? 'freq' : 'bayes'
    }
    const method = latest?.results.find((row) => row.result?.variant_results?.length)?.result?.variant_results?.[0]
        ?.method
    return method === 'frequentist' ? 'freq' : 'bayes'
}

export function daysOf(
    experiment: Pick<ExperimentListItemApi, 'start_date' | 'end_date'>,
    now: number = Date.now()
): number | null {
    if (!experiment.start_date) {
        return null
    }
    const start = Date.parse(experiment.start_date)
    const end = experiment.end_date ? Date.parse(experiment.end_date) : now
    if (Number.isNaN(start) || Number.isNaN(end)) {
        return null
    }
    return Math.max(0, Math.floor((end - start) / DAY_MS))
}

export function isNewLaunch(experiment: Pick<ExperimentListItemApi, 'start_date'>, now: number = Date.now()): boolean {
    const start = experiment.start_date ? Date.parse(experiment.start_date) : Number.NaN
    return !Number.isNaN(start) && now - start >= 0 && now - start < NEW_LAUNCH_MS
}

function displayName(user: ExperimentListItemApi['created_by'] | null | undefined): ExperimentRow['createdBy'] {
    if (!user) {
        return null
    }
    const name = [user.first_name, user.last_name].filter(Boolean).join(' ').trim()
    return { uuid: user.uuid, name: name || user.email, email: user.email }
}

export function rowOf(
    experiment: ExperimentListItemApi,
    headline: RowHeadline,
    changed: boolean,
    now: number = Date.now()
): ExperimentRow {
    const status = experimentStatusOf(experiment)
    return {
        id: String(experiment.id),
        name: experiment.name,
        flagKey: experiment.feature_flag_key,
        status,
        method: typeof headline === 'string' ? methodOf(experiment) : (headline.method ?? methodOf(experiment)),
        variants: variantKeysOf(experiment),
        startedAt: experiment.start_date ?? null,
        endedAt: experiment.end_date ?? null,
        createdAt: experiment.created_at,
        days: daysOf(experiment, now),
        conclusion: experiment.conclusion ?? null,
        shippedVariant: status === 'complete' ? shippedVariantOf(experiment) : null,
        changed,
        headline,
        createdBy: displayName(experiment.created_by),
        isNew: isLiveStatus(status) && isNewLaunch(experiment, now),
        targetSampleSize: experiment.running_time_calculation?.recommended_sample_size ?? null,
    }
}

export type MetricRole = 'primary' | 'secondary'

/** One metric definition in display order, as the experiment API returns it. */
export interface MetricEntry {
    /** The metric JSON: the experiment's own, or a shared metric's `effective_query` (else `query`). */
    raw: Record<string, unknown>
    /** A shared metric's name, which the web shows instead of the query's own. Null for the experiment's own. */
    savedName: string | null
    metric: ResultMetric
}

/**
 * The web's `getDisplayOrderedIndices`: indices whose uuid is listed come first in the list's order, then the rest in
 * array order. The list is a display hint, so an unknown uuid is skipped and an unlisted metric still shows.
 */
export function displayOrderedIndices(
    metrics: readonly { uuid?: unknown }[],
    orderedUuids: readonly string[] | null | undefined
): number[] {
    if (!orderedUuids?.length) {
        return metrics.map((_, index) => index)
    }
    const indexByUuid = new Map<string, number>()
    metrics.forEach((metric, index) => {
        if (typeof metric.uuid === 'string' && metric.uuid) {
            indexByUuid.set(metric.uuid, index)
        }
    })
    const ordered: number[] = []
    const seen = new Set<number>()
    for (const uuid of orderedUuids) {
        const index = indexByUuid.get(uuid)
        if (index !== undefined && !seen.has(index)) {
            ordered.push(index)
            seen.add(index)
        }
    }
    metrics.forEach((_, index) => {
        if (!seen.has(index)) {
            ordered.push(index)
        }
    })
    return ordered
}

function metricOf(raw: Record<string, unknown>, savedName: string | null, role: MetricRole): ResultMetric {
    const ownName = typeof raw.name === 'string' && raw.name.trim() ? raw.name.trim() : null
    return {
        uuid: typeof raw.uuid === 'string' ? raw.uuid : null,
        name: savedName ?? ownName ?? (role === 'primary' ? 'Primary metric' : 'Secondary metric'),
        goal: raw.goal === 'decrease' ? 'decrease' : 'increase',
        metricType: typeof raw.metric_type === 'string' ? raw.metric_type : 'mean',
    }
}

/**
 * The web's `metricResults` order for one role: the experiment's own metrics and the shared metrics whose
 * `metadata.type` names the role, together, ordered by the role's `*_metrics_ordered_uuids`.
 */
export function orderedMetricsOf(experiment: ExperimentApi, role: MetricRole): MetricEntry[] {
    const own = ((role === 'primary' ? experiment.metrics : experiment.metrics_secondary) ?? []) as unknown[]
    const entries: MetricEntry[] = own
        .filter(isRecord)
        .map((raw) => ({ raw, savedName: null, metric: metricOf(raw, null, role) }))
    for (const saved of experiment.saved_metrics ?? []) {
        const metadata = isRecord(saved.metadata) ? saved.metadata : {}
        const query = saved.effective_query ?? saved.query
        if (metadata.type === role && isRecord(query)) {
            entries.push({ raw: query, savedName: saved.name, metric: metricOf(query, saved.name, role) })
        }
    }
    const order =
        role === 'primary' ? experiment.primary_metrics_ordered_uuids : experiment.secondary_metrics_ordered_uuids
    return displayOrderedIndices(
        entries.map((entry) => entry.raw),
        order
    ).flatMap((index) => {
        const entry = entries[index]
        return entry ? [entry] : []
    })
}

/** The primary metrics in the web's display order. The first one drives a row's headline. */
export function primaryMetricsOf(experiment: ExperimentApi): ResultMetric[] {
    return orderedMetricsOf(experiment, 'primary').map((entry) => entry.metric)
}

export function secondaryMetricsOf(experiment: ExperimentApi): ResultMetric[] {
    return orderedMetricsOf(experiment, 'secondary').map((entry) => entry.metric)
}

function metricValueOf(stats: ExperimentStatsApi, metricType: string): number | null {
    if (metricType === 'quantile') {
        const value = stats.quantile_grid?.[0]
        return typeof value === 'number' && Number.isFinite(value) ? value : null
    }
    if (metricType === 'ratio') {
        return stats.denominator_sum ? stats.sum / stats.denominator_sum : null
    }
    return stats.number_of_samples > 0 ? stats.sum / stats.number_of_samples : null
}

function intervalOf(result: ExperimentVariantResultApi): [number, number] | null {
    const interval = result.method === 'frequentist' ? result.confidence_interval : result.credible_interval
    const fallback = interval ?? result.credible_interval ?? result.confidence_interval
    if (
        !fallback ||
        fallback.length !== 2 ||
        typeof fallback[0] !== 'number' ||
        !Number.isFinite(fallback[0]) ||
        typeof fallback[1] !== 'number' ||
        !Number.isFinite(fallback[1])
    ) {
        return null
    }
    return [fallback[0], fallback[1]]
}

function variantResultOf(
    result: ExperimentVariantResultApi,
    metric: ResultMetric,
    differenceType: ExperimentDifferenceType
): VariantResult | null {
    const interval = intervalOf(result)
    if (!interval) {
        return null
    }
    const delta = (interval[0] + interval[1]) / 2
    const decrease = metric.goal === 'decrease'
    const chance = typeof result.chance_to_win === 'number' ? result.chance_to_win : undefined
    return {
        key: result.key,
        samples: result.number_of_samples,
        value: metricValueOf(result, metric.metricType),
        delta,
        differenceType,
        interval,
        chanceToWin: chance === undefined ? undefined : decrease ? 1 - chance : chance,
        pValue: typeof result.p_value === 'number' ? result.p_value : undefined,
        significant: result.significant === true,
        better: decrease ? delta < 0 : delta > 0,
    }
}

/** The stored result of a metric, or null while it is pending, failed or missing. */
export function metricResultOf(
    latest: ExperimentResultsRunApi | null | undefined,
    metric: ResultMetric
): ExperimentQueryResultApi | null {
    if (!latest || !metric.uuid) {
        return null
    }
    const row = latest.results.find((candidate) => candidate.metric_uuid === metric.uuid)
    return row?.status === 'completed' ? row.result : null
}

export function resultOf(
    metric: ResultMetric,
    result: ExperimentQueryResultApi | null,
    differenceType: ExperimentDifferenceType = 'relative'
): PrimaryResult | null {
    if (!result?.baseline || !result.variant_results?.length) {
        return null
    }
    const variants = result.variant_results
        .map((variant) => variantResultOf(variant, metric, differenceType))
        .filter((variant): variant is VariantResult => variant !== null)
    if (!variants.length) {
        return null
    }
    return {
        metric,
        baseline: {
            key: result.baseline.key,
            samples: result.baseline.number_of_samples,
            value: metricValueOf(result.baseline, metric.metricType),
        },
        variants,
    }
}

export function primaryResultOf(
    experiment: ExperimentApi,
    latest: ExperimentResultsRunApi | null | undefined
): PrimaryResult | null {
    const metric = primaryMetricsOf(experiment)[0]
    const config = experiment.stats_config
    const method = methodOf(experiment, latest) === 'freq' ? 'frequentist' : 'bayesian'
    const settings = isRecord(config) ? config[method] : undefined
    const differenceType = isRecord(settings) && settings.difference_type === 'ABSOLUTE' ? 'absolute' : 'relative'
    return metric ? resultOf(metric, metricResultOf(latest, metric), differenceType) : null
}

export function exposuresOf(primary: PrimaryResult): number {
    return primary.baseline.samples + primary.variants.reduce((sum, variant) => sum + variant.samples, 0)
}

/**
 * The variant a reader looks at first: a significant better one, else a significant worse one, else the one most
 * likely to win (Bayesian) or with the lowest p-value (Frequentist).
 */
export function leaderOf(primary: PrimaryResult): VariantResult | null {
    const byStrength = (a: VariantResult, b: VariantResult): number =>
        (b.chanceToWin ?? 0) - (a.chanceToWin ?? 0) ||
        (a.pValue ?? 1) - (b.pValue ?? 1) ||
        Math.abs(b.delta) - Math.abs(a.delta)
    const significant = primary.variants.filter((variant) => variant.significant)
    const winners = significant.filter((variant) => variant.better)
    if (winners.length) {
        return [...winners].sort(byStrength)[0] ?? null
    }
    if (significant.length) {
        return [...significant].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))[0] ?? null
    }
    return [...primary.variants].sort(byStrength)[0] ?? null
}

function targetReached(experiment: ExperimentApi | ExperimentListItemApi, exposures: number): boolean {
    const target = experiment.running_time_calculation?.recommended_sample_size
    return typeof target === 'number' && target > 0 && exposures >= target
}

/** The one-line answer a list row shows. `none` for drafts and experiments without a primary metric. */
export function headlineOf(
    experiment: ExperimentApi,
    latest: ExperimentResultsRunApi | null | undefined
): HeadlineResult | 'none' {
    const status = experimentStatusOf(experiment)
    if (status === 'draft' || !primaryMetricsOf(experiment).length) {
        return 'none'
    }
    const resultsAt = latest ? (latest.query_to ?? latest.completed_at ?? undefined) : undefined
    const method = methodOf(experiment, latest)
    const primary = primaryResultOf(experiment, latest)
    if (!primary) {
        return { kind: 'not_yet', method, resultsAt }
    }
    const exposures = exposuresOf(primary)
    const leader = leaderOf(primary)
    if (!leader) {
        return { kind: 'needs_data', method, exposures, resultsAt }
    }
    const base: HeadlineResult = {
        kind: 'needs_data',
        method,
        leader: leader.key,
        delta: leader.delta,
        differenceType: leader.differenceType,
        better: leader.better,
        chanceToWin: leader.chanceToWin,
        pValue: leader.pValue,
        exposures,
        resultsAt,
    }
    if (leader.significant) {
        return { ...base, kind: 'significant' }
    }
    if (targetReached(experiment, exposures)) {
        return { ...base, kind: 'target' }
    }
    const leading =
        leader.better &&
        (leader.chanceToWin !== undefined
            ? leader.chanceToWin >= LEADING_CHANCE
            : leader.pValue !== undefined && leader.pValue < LEADING_P_VALUE)
    return { ...base, kind: leading ? 'leading' : 'needs_data' }
}

/** A short stable string for the "changed since last look" dot. Rounding keeps small drifts from lighting it. */
export function headlineKey(headline: RowHeadline): string | null {
    if (typeof headline === 'string') {
        return null
    }
    return [
        headline.kind,
        headline.leader ?? '',
        headline.better === undefined ? '' : headline.better ? 'up' : 'down',
    ].join('|')
}

/** Won when a variant is significantly better, lost when the leader is significantly worse, else inconclusive. */
export function suggestedConclusion(primary: PrimaryResult | null): 'won' | 'lost' | 'inconclusive' | null {
    if (!primary) {
        return null
    }
    const leader = leaderOf(primary)
    if (leader?.significant) {
        return leader.better ? 'won' : 'lost'
    }
    return 'inconclusive'
}

export function needsDecision(row: ExperimentRow): boolean {
    return typeof row.headline !== 'string' && (row.headline.kind === 'significant' || row.headline.kind === 'target')
}

function timeOf(value: string | null): number {
    const parsed = value ? Date.parse(value) : Number.NaN
    return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed
}

function byNameThenId(a: ExperimentRow, b: ExperimentRow): number {
    return a.name.localeCompare(b.name) || a.id.localeCompare(b.id)
}

/** Needs a decision first, then changed since the last look, then the newest launch. */
export function sortRunning(rows: readonly ExperimentRow[]): ExperimentRow[] {
    return [...rows].sort(
        (a, b) =>
            Number(needsDecision(b)) - Number(needsDecision(a)) ||
            Number(b.changed) - Number(a.changed) ||
            timeOf(b.startedAt) - timeOf(a.startedAt) ||
            byNameThenId(a, b)
    )
}

export function sortDone(rows: readonly ExperimentRow[]): ExperimentRow[] {
    return [...rows].sort((a, b) => timeOf(b.endedAt) - timeOf(a.endedAt) || byNameThenId(a, b))
}

export function sortDrafts(rows: readonly ExperimentRow[]): ExperimentRow[] {
    return [...rows].sort((a, b) => timeOf(b.createdAt) - timeOf(a.createdAt) || byNameThenId(a, b))
}

export interface Freshness {
    resultsAt: Date | null
    ageMs: number | null
    /**
     * `fallback`: the daily timeseries placeholder (`result_source: timeseries_fallback`). `manual` and `daily` need
     * the run's trigger, which the API does not return, so a recalculation run reads as null.
     */
    source: 'daily' | 'manual' | 'fallback' | null
}

export function freshnessOf(latest: ExperimentResultsRunApi | null | undefined, now: number = Date.now()): Freshness {
    const stamp = latest ? (latest.query_to ?? latest.completed_at) : null
    const parsed = stamp ? Date.parse(stamp) : Number.NaN
    const resultsAt = Number.isNaN(parsed) ? null : new Date(parsed)
    const trigger = isRecord(latest) && typeof latest.trigger === 'string' ? latest.trigger : null
    let source: Freshness['source'] = null
    if (latest?.result_source === 'timeseries_fallback') {
        source = 'fallback'
    } else if (trigger === 'manual' || trigger === 'manual_retry') {
        source = 'manual'
    } else if (trigger === 'scheduled' || trigger === 'timeseries_sync') {
        source = 'daily'
    }
    return { resultsAt, ageMs: resultsAt ? Math.max(0, now - resultsAt.getTime()) : null, source }
}

function trimHost(host: string): string {
    return host.replace(/\/+$/, '')
}

export function webExperimentUrl(host: string, projectId: number, id: string | number): string {
    return `${trimHost(host)}/project/${projectId}/experiments/${encodeURIComponent(String(id))}`
}

export function webFlagUrl(host: string, projectId: number, flagId: string | number): string {
    return `${trimHost(host)}/project/${projectId}/feature_flags/${encodeURIComponent(String(flagId))}`
}
