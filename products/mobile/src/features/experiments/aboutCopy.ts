import { formatClock, formatMonthDay } from '@/lib/dates'

import {
    type CellModel,
    type ChangeUnit,
    formatAlpha,
    formatChance,
    formatChangeSize,
    formatCount,
    formatDelta,
    formatLevel,
    formatMetricValue,
    formatPValue,
    type IntervalSide,
    type MetricCardModel,
    type MetricDef,
    methodLabel,
    type ProgressModel,
    progressLabel,
    type StatsSettings,
    valueNoun,
} from './detailModel'

// The plain-language copy of the "About this number" sheet. Bayesian results speak of a chance to win and a credible
// interval, Frequentist ones of a p-value and a confidence interval, and a `decrease` goal turns "better" around.

/** What a reader tapped. `chance` on a Frequentist card reads as `p_value`. */
export type AboutWhat = 'chance' | 'delta' | 'value' | 'control' | 'p_value' | 'target'

export interface AboutRow {
    label: string
    value: string
    sub?: string
}

export interface AboutFigure {
    caption: string
    interval: [number, number]
    delta: number
    unit: ChangeUnit
    scale: number
    side: IntervalSide
}

export interface AboutKicker {
    /** The variant chip, or null for the progress sheet. */
    variantKey: string | null
    colorIndex: number
    /** The baseline a variant is compared with, or null for the baseline itself and the progress sheet. */
    versus: string | null
    context: string
}

export interface AboutCopy {
    what: AboutWhat
    kicker: AboutKicker
    title: string
    tone: 'good' | 'bad' | 'plain'
    lead: string
    figure: AboutFigure | null
    rows: AboutRow[]
    foot: string
    runLine: string | null
}

export interface MetricAboutInput {
    what: Exclude<AboutWhat, 'target'>
    card: MetricCardModel
    variantKey: string
    settings: StatsSettings
    /** The time the results cover data up to. */
    runAt: Date | null
    clock24?: boolean
}

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1)
}

function chanceWords(chance: number): string {
    if (chance >= 0.999) {
        return 'more than 99.9%'
    }
    if (chance <= 0.001) {
        return 'less than 0.1%'
    }
    return formatChance(chance)
}

/** `a 64.0%`, `an 87.4%`: the article follows how the number is read aloud. */
function withArticle(amount: string): string {
    return /^(8|11(\D|$)|18(\D|$))/.test(amount) ? `an ${amount}` : `a ${amount}`
}

function pWords(p: number): string {
    return p < 0.001 ? 'less than 0.1%' : `${(p * 100).toFixed(1)}%`
}

function toneOf(cell: CellModel): AboutCopy['tone'] {
    if (!cell.significant || cell.better === null) {
        return 'plain'
    }
    return cell.better ? 'good' : 'bad'
}

function intervalName(settings: StatsSettings): string {
    return settings.method === 'freq' ? 'confidence interval' : 'credible interval'
}

function runLineOf(runAt: Date | null, clock24?: boolean): string | null {
    return runAt ? `From the ${formatMonthDay(runAt)}, ${formatClock(runAt, clock24)} run.` : null
}

/**
 * Why a variant is or is not significant, by the rule the server applies: a Bayesian result when the chance to win
 * passes the interval level either way (`is_decisive`), a Frequentist one when the confidence interval leaves out 0.
 */
export function significanceRow(cell: CellModel, settings: StatsSettings): AboutRow {
    if (settings.method === 'freq') {
        const [low, high] = cell.interval ?? [0, 0]
        if (cell.significant) {
            const sub =
                low > 0
                    ? 'the whole range is above 0'
                    : high < 0
                      ? 'the whole range is below 0'
                      : `p is under ${formatAlpha(settings.alpha)}`
            return { label: 'Significant', value: 'Yes', sub }
        }
        const sub = low <= 0 && high >= 0 ? 'the range includes 0' : `p is ${formatAlpha(settings.alpha)} or more`
        return { label: 'Significant', value: 'No', sub }
    }
    const level = formatLevel(settings.level)
    const floor = formatLevel(1 - settings.level)
    const chance = cell.chanceToWin
    if (cell.significant && chance !== null) {
        return {
            label: 'Significant',
            value: 'Yes',
            sub: chance >= 0.5 ? `chance to win is above ${level}` : `chance to win is below ${floor}`,
        }
    }
    return { label: 'Significant', value: 'No', sub: `chance to win is between ${floor} and ${level}` }
}

function valueSentence(def: MetricDef, cell: CellModel): string {
    const value = formatMetricValue(def.kind, cell.value)
    const people = formatCount(cell.samples)
    switch (def.kind) {
        case 'rate':
            return cell.numerator === null
                ? `${value} of the ${people} people who saw ${cell.key} ${def.rateVerb}.`
                : `${formatCount(cell.numerator)} of the ${people} people who saw ${cell.key} ${def.rateVerb}.`
        case 'mean':
            return `People who saw ${cell.key} averaged ${value}, across ${people} people.`
        default:
            return `${cell.key}'s ${valueNoun(def)} is ${value}, across ${people} people.`
    }
}

function comparisonRows(
    card: MetricCardModel,
    cell: CellModel,
    baseline: CellModel,
    settings: StatsSettings
): AboutRow[] {
    const { def } = card
    const rows: AboutRow[] = [
        {
            label: capitalize(valueNoun(def)),
            value: `${formatMetricValue(def.kind, cell.value)} vs ${formatMetricValue(def.kind, baseline.value)}`,
            sub: `${cell.key} vs ${baseline.key}`,
        },
    ]
    if (cell.delta !== null && cell.interval) {
        rows.push({
            label: 'Change',
            value: formatDelta(cell.delta, card.unit),
            sub: `${formatDelta(cell.interval[0], card.unit)} to ${formatDelta(cell.interval[1], card.unit)}, ${formatLevel(settings.level)}`,
        })
    }
    rows.push(significanceRow(cell, settings))
    rows.push({
        label: 'People in this metric',
        value: `${formatCount(cell.samples)} vs ${formatCount(baseline.samples)}`,
    })
    return rows
}

function baselineCopy(input: MetricAboutInput, baseline: CellModel): AboutCopy {
    const { card, settings, runAt, clock24 } = input
    const { def } = card
    const freq = settings.method === 'freq'
    const value = formatMetricValue(def.kind, baseline.value)
    const people = formatCount(baseline.samples)
    let sentence: string
    if (def.kind === 'rate') {
        sentence =
            baseline.numerator === null
                ? `${value} of the ${people} people who saw ${baseline.key} ${def.rateVerb}.`
                : `${formatCount(baseline.numerator)} of the ${people} people who saw ${baseline.key} ${def.rateVerb} (${value}).`
    } else {
        sentence = valueSentence(def, baseline)
    }
    const rows: AboutRow[] = [
        { label: capitalize(valueNoun(def)), value },
        { label: 'People in this metric', value: people },
    ]
    if (def.kind === 'rate' && baseline.numerator !== null) {
        rows.push({ label: capitalize(def.rateVerb), value: formatCount(baseline.numerator) })
    }
    return {
        what: 'control',
        kicker: { variantKey: baseline.key, colorIndex: baseline.colorIndex, versus: null, context: def.name },
        title: `${baseline.key} is the baseline`,
        tone: 'plain',
        lead: `Every change and ${freq ? 'p-value' : 'chance to win'} on this card compares a variant with ${baseline.key}. ${sentence}`,
        figure: null,
        rows,
        foot: `To see how a variant compares, tap its change or its ${freq ? 'p-value' : 'chance to win'}.`,
        runLine: runLineOf(runAt, clock24),
    }
}

/** The sheet for one cell or column label of a metric card. Null when the card has no result for that variant. */
export function metricAboutCopy(input: MetricAboutInput): AboutCopy | null {
    const { card, variantKey, settings, runAt, clock24 } = input
    const baseline = card.baseline
    if (card.state !== 'ready' || !baseline) {
        return null
    }
    if (input.what === 'control' || variantKey === baseline.key) {
        return baselineCopy(input, baseline)
    }
    const cell = card.variants.find((variant) => variant.key === variantKey)
    if (!cell || cell.delta === null || !cell.interval) {
        return null
    }
    const { def } = card
    const freq = settings.method === 'freq'
    const what: AboutWhat =
        input.what === 'chance' && freq ? 'p_value' : input.what === 'p_value' && !freq ? 'chance' : input.what
    const level = formatLevel(settings.level)
    const noun = valueNoun(def)
    const decrease = def.goal === 'decrease'
    const rows = comparisonRows(card, cell, baseline, settings)
    const kicker: AboutKicker = {
        variantKey: cell.key,
        colorIndex: cell.colorIndex,
        versus: baseline.key,
        context: def.name,
    }
    const figure: AboutFigure = {
        caption: `Change vs ${baseline.key} · ${level} ${intervalName(settings)}`,
        interval: cell.interval,
        delta: cell.delta,
        unit: card.unit,
        scale: card.scale,
        side: cell.side,
    }
    const base = { kicker, figure, runLine: runLineOf(runAt, clock24) }
    const tone = toneOf(cell)
    const [low, high] = cell.interval

    if (what === 'value') {
        return {
            ...base,
            what,
            title:
                def.kind === 'quantile'
                    ? `${capitalize(noun)} of ${formatMetricValue(def.kind, cell.value)}`
                    : `${formatMetricValue(def.kind, cell.value)} ${noun}`,
            tone: 'plain',
            lead: valueSentence(def, cell),
            rows,
            foot: 'People in this metric can differ from the exposure totals. Each metric counts people when they enter it.',
        }
    }

    if (what === 'delta') {
        const { unit } = card
        const size = formatChangeSize(cell.delta, unit)
        const estimate =
            size === formatChangeSize(0, unit)
                ? `The best estimate is that ${cell.key}'s ${noun} is about the same as ${baseline.key}'s.`
                : `The best estimate is that ${cell.key}'s ${noun} is ${size} ${cell.delta > 0 ? 'higher' : 'lower'} than ${baseline.key}'s.`
        const range = freq
            ? `The ${level} confidence interval for the real change runs from ${formatDelta(low, unit)} to ${formatDelta(high, unit)}.`
            : `There's a ${level} chance the real change is between ${formatDelta(low, unit)} and ${formatDelta(high, unit)}.`
        const unitNote: Record<ChangeUnit, string> = {
            relative: `The change is relative to ${baseline.key}: +10% means 10% more than ${baseline.key}'s ${noun}${def.kind === 'rate' ? ', not 10 points more' : ''}.`,
            points: `The change is in percentage points: +2 pts means 2 points more than ${baseline.key}'s ${noun}.`,
            units: `The change is in the metric's units: +2 means 2 more than ${baseline.key}'s ${noun}.`,
        }
        const rule = freq
            ? 'A variant is significant when the whole range sits on one side of 0.'
            : `A variant is significant when its chance to win is above ${level} or below ${formatLevel(1 - settings.level)}.`
        return {
            ...base,
            what,
            title: `${formatDelta(cell.delta, unit)} change`,
            tone,
            lead: `${estimate} ${range}`,
            rows,
            foot: `${unitNote[unit]} ${rule}`,
        }
    }

    if (what === 'p_value') {
        const p = cell.pValue
        if (p === null) {
            return null
        }
        const alpha = formatAlpha(settings.alpha)
        const direction = cell.delta < 0 ? 'drop' : 'lift'
        const verdict = cell.significant
            ? `That's under the ${alpha} cut-off, so the ${direction} is significant.`
            : p < settings.alpha
              ? `That's under the ${alpha} cut-off, but the result isn't significant yet.`
              : `That's above the ${alpha} cut-off, so it isn't significant yet.`
        return {
            ...base,
            what,
            title: p < 0.001 ? 'p < 0.001' : `p = ${formatPValue(p)}`,
            tone,
            lead: `If ${cell.key} and ${baseline.key} really performed the same, a difference at least this big would show up ${pWords(p)} of the time. ${verdict}`,
            rows: [...rows, { label: 'Method', value: methodLabel(settings) }],
            foot: 'Frequentist results show a p-value where Bayesian ones show chance to win. A lower p-value means stronger evidence of a real difference.',
        }
    }

    const chance = cell.chanceToWin
    if (chance === null) {
        return null
    }
    return {
        ...base,
        what: 'chance',
        title: `${formatChance(chance)} chance to win`,
        tone,
        lead: `${decrease ? 'Lower is better here. ' : ''}Given the data so far, there's ${withArticle(chanceWords(chance))} chance ${cell.key} has a ${decrease ? 'lower' : 'higher'} ${noun} than ${baseline.key}.`,
        rows: [...rows, { label: 'Goal', value: decrease ? 'Lower is better' : 'Higher is better' }],
        foot: `Chance to win says how likely a variant beats ${baseline.key}, not by how much. The change and its range show how much.`,
    }
}

export interface TargetAboutInput {
    progress: ProgressModel
    name: string
    /** `12 days`, `38 min`. Null hides the row. */
    runningFor: string | null
}

export function targetAboutCopy({ progress, name, runningFor }: TargetAboutInput): AboutCopy {
    const current = formatCount(progress.current)
    const recommended = progress.recommended === null ? null : formatCount(progress.recommended)
    let lead: string
    if (progress.state === 'early' || recommended === null) {
        lead = `${current} exposures so far. The estimate needs more results before it can say how long this takes.`
    } else if (progress.state === 'reached') {
        lead =
            progress.minimumEffect === null
                ? `${name} has ${current} exposures. The recommended sample size is ${recommended}.`
                : `${name} has ${current} exposures. The recommended sample size is ${recommended}, which is enough to detect a change of ${formatDecimalPercent(progress.minimumEffect)} or more.`
    } else {
        const pace =
            progress.perDay && progress.daysToGo !== null
                ? ` At about ${formatCount(progress.perDay)} a day, that's about ${progress.daysToGo} more ${progress.daysToGo === 1 ? 'day' : 'days'}.`
                : ''
        lead = `${current} of the ${recommended} recommended exposures.${pace}`
    }
    const rows: AboutRow[] = [
        { label: 'Exposures now', value: current },
        { label: 'Recommended', value: recommended ?? 'Not known yet' },
    ]
    if (runningFor) {
        rows.push({ label: 'Running for', value: runningFor })
    }
    if (progress.perDay) {
        rows.push({ label: 'Pace', value: `About ${formatCount(progress.perDay)} a day` })
    }
    if (progress.minimumEffect !== null) {
        rows.push({ label: 'Smallest change to detect', value: formatDecimalPercent(progress.minimumEffect) })
    }
    return {
        what: 'target',
        kicker: { variantKey: null, colorIndex: 0, versus: null, context: name },
        title: progressLabel(progress),
        tone: progress.state === 'reached' ? 'good' : 'plain',
        lead,
        figure: null,
        rows,
        foot: 'The recommended size comes from the smallest change the experiment is set up to detect.',
        runLine: null,
    }
}

/** `minimum_detectable_effect` is already a percentage. */
function formatDecimalPercent(percent: number): string {
    return Number.isInteger(percent) ? `${percent}%` : `${percent.toFixed(1)}%`
}
