import { BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'

import { NodeKind } from '~/queries/schema/schema-general'
import type { InsightVizNode, Node, TrendsQuery } from '~/queries/schema/schema-general'
import { isActionsNode, isEventsNode, isTrendsQuery } from '~/queries/utils'
import { BaseMathType, ChartDisplayType, PropertyMathType } from '~/types'
import type { IntervalType } from '~/types'

import type { ChartCauseEnumApi } from 'products/product_analytics/frontend/generated/api.schemas'
import { mark } from 'products/product_analytics/mcp/apps/explainChart/storyMarks'

import type { ChartMoment } from './chartMoments'

export interface MomentEvidence {
    text: string
    /** The chart that the statement comes from. Null when it sums up several charts. */
    query: InsightVizNode | null
    /** The share of the change that the statement puts on one thing, such as one page. Null when it names nothing. */
    driverShare: number | null
    /** The property value that carries the change, such as one page. Null when the statement names none. */
    driver: { key: string; value: string } | null
    /** The cause that the statement shows on its own, without the model. */
    cause: ChartCauseEnumApi | null
}

interface EvidenceProperty {
    key: string
    noun: string
}

const EVIDENCE_PROPERTIES: EvidenceProperty[] = [
    { key: '$pathname', noun: 'page' },
    { key: '$referring_domain', noun: 'referrer' },
    { key: '$geoip_country_name', noun: 'country' },
    { key: '$browser', noun: 'browser' },
    { key: '$device_type', noun: 'device type' },
    { key: '$host', noun: 'host' },
]

const MAX_DRIVERS = 2
/** A value explains a change when it carries most of it, and much more of it than its usual share. */
const MIN_CONTRIBUTION = 0.5
const MIN_SURPRISE = 0.25

export interface EvidenceQueries {
    breakdowns: { property: EvidenceProperty; query: TrendsQuery }[]
    people: TrendsQuery | null
}

export interface EvidenceRow {
    breakdown_value?: string | number | string[] | null
    data: number[]
}

export interface EvidenceResults {
    breakdowns: { property: EvidenceProperty; query: TrendsQuery; rows: EvidenceRow[] }[]
    people: { query: TrendsQuery; data: number[] } | null
}

export interface EvidenceContext {
    values: number[]
    completePoints: number
    interval: IntervalType
    formatValue: (value: number) => string
}

/** The chart's own query, split by each property that can explain a change. Null when the chart cannot be split. */
export function buildEvidenceQueries(source: Node | null | undefined, seriesIndex: number): EvidenceQueries | null {
    if (!isTrendsQuery(source)) {
        return null
    }
    const { breakdownFilter, trendsFilter } = source
    const hasBreakdown = !!breakdownFilter?.breakdown || !!breakdownFilter?.breakdowns?.length
    const hasFormula =
        !!trendsFilter?.formula || !!trendsFilter?.formulas?.length || !!trendsFilter?.formulaNodes?.length
    const node = source.series[seriesIndex]
    // A split explains a share of the change only when the values of its parts add up to the chart's value.
    const additive = !node?.math || node.math === BaseMathType.TotalCount || node.math === PropertyMathType.Sum
    if (hasBreakdown || hasFormula || !additive || (!isEventsNode(node) && !isActionsNode(node))) {
        return null
    }
    const base: TrendsQuery = {
        ...source,
        series: [node],
        compareFilter: undefined,
        trendsFilter: { ...trendsFilter, display: ChartDisplayType.ActionsLineGraph },
    }
    const countsEvents = !node.math || node.math === BaseMathType.TotalCount
    return {
        breakdowns: EVIDENCE_PROPERTIES.map((property) => ({
            property,
            query: {
                ...base,
                breakdownFilter: { breakdown: property.key, breakdown_type: 'event', breakdown_limit: 8 },
            },
        })),
        people: countsEvents ? { ...base, series: [{ ...node, math: BaseMathType.UniqueUsers }] } : null,
    }
}

function mean(values: number[]): number {
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0
}

function median(values: number[]): number {
    if (!values.length) {
        return 0
    }
    const sorted = [...values].sort((a, b) => a - b)
    const middle = Math.floor(sorted.length / 2)
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function percent(share: number): string {
    return `${Math.round(Math.min(Math.max(share, 0), 1) * 100)}%`
}

function valueLabel(value: EvidenceRow['breakdown_value']): string {
    const text = Array.isArray(value) ? value.join(', ') : String(value ?? '')
    return text === BREAKDOWN_NULL_STRING_LABEL || text === '' ? 'not set' : text
}

function asViz(query: TrendsQuery): InsightVizNode {
    return { kind: NodeKind.InsightVizNode, source: query }
}

interface Driver {
    property: EvidenceProperty
    query: TrendsQuery
    value: string
    contribution: number
    usual: number
}

function driverOf(
    breakdown: EvidenceResults['breakdowns'][number],
    window: number[],
    rest: number[],
    direction: 'up' | 'down'
): Driver | null {
    const rows = breakdown.rows.map((row) => ({
        row,
        inWindow: mean(window.map((index) => row.data[index] ?? 0)),
        inRest: mean(rest.map((index) => row.data[index] ?? 0)),
    }))
    const totalInWindow = rows.reduce((sum, row) => sum + row.inWindow, 0)
    const totalInRest = rows.reduce((sum, row) => sum + row.inRest, 0)
    const change = totalInWindow - totalInRest
    if (direction === 'up' ? change <= 0 : change >= 0) {
        return null
    }
    let best: Driver | null = null
    for (const { row, inWindow, inRest } of rows) {
        if (String(row.breakdown_value) === BREAKDOWN_OTHER_STRING_LABEL) {
            continue
        }
        const contribution = (inWindow - inRest) / change
        if (!best || contribution > best.contribution) {
            best = {
                property: breakdown.property,
                query: breakdown.query,
                value: valueLabel(row.breakdown_value),
                contribution,
                usual: totalInRest > 0 ? inRest / totalInRest : 0,
            }
        }
    }
    return best
}

function peopleEvidence(
    moment: ChartMoment,
    people: NonNullable<EvidenceResults['people']>,
    rest: number[],
    context: EvidenceContext
): MomentEvidence | null {
    if (moment.kind !== 'peak') {
        return null
    }
    const [start, end] = moment.range
    let anchor = start
    for (let index = start; index <= end; index++) {
        if (context.values[index] > context.values[anchor]) {
            anchor = index
        }
    }
    const count = people.data[anchor]
    if (!count) {
        return null
    }
    const each = context.values[anchor] / count
    const active = rest.filter((index) => people.data[index] > 0)
    const typicalCount = median(active.map((index) => people.data[index]))
    const typicalEach = median(active.map((index) => context.values[index] / people.data[index]))
    const unit = context.interval
    const whole = (value: number): string => context.formatValue(Math.round(value))
    const sentences = [
        count === 1
            ? `${mark('value', 'One person')} did all of it.`
            : each < 1.5
              ? `${mark('value', `${whole(count)} different people`)} did this, about once each.`
              : `${mark('value', `${whole(count)} people`)} did this, about ${whole(each)} times each.`,
    ]
    if (typicalCount > 0) {
        const typicalPeople = Math.round(typicalCount) === 1 ? '1 person' : `${whole(typicalCount)} people`
        sentences.push(
            typicalEach < 1.5
                ? `A typical ${unit} has ${typicalPeople}.`
                : `A typical ${unit} has ${typicalPeople}, at about ${whole(typicalEach)} times each.`
        )
        const morePeople = count >= typicalCount * 1.5
        const moreEach = each >= typicalEach * 1.5
        if (morePeople && moreEach) {
            sentences.push('So more people came, and each one did more.')
        } else if (morePeople) {
            sentences.push('So it was more people, not more activity from each one.')
        } else if (moreEach && count > 1) {
            sentences.push('So it was about the same people doing much more.')
        }
    }
    return {
        text: sentences.join(' '),
        query: asViz(people.query),
        driverShare: count === 1 ? 1 : null,
        driver: null,
        cause: count === 1 ? 'one_person' : null,
    }
}

function siteOf(domain: string): string {
    return domain.toLowerCase().replace(/^www\./, '')
}

function driverPhrase(driver: Driver, hosts: Set<string>): string {
    const name = mark('name', driver.value)
    if (driver.property.key === '$host') {
        return `happened on ${name}`
    }
    // A referrer that is one of the chart's own hosts is people moving around the site, not an outside source.
    if (driver.property.key === '$referring_domain' && hosts.has(siteOf(driver.value))) {
        return `came from people already on ${name}`
    }
    return `came from the ${driver.property.noun} ${name}`
}

/** What the split charts say about the cause of a peak, a dip or a change of level. */
export function evidenceForMoment(
    moment: ChartMoment,
    results: EvidenceResults,
    context: EvidenceContext
): MomentEvidence[] {
    const [start, end] = moment.range
    const inWindow = (index: number): boolean => index >= start && index <= end
    const complete = Array.from({ length: context.completePoints }, (_, index) => index)
    const window = complete.filter(inWindow)
    // A shift is a change from the level before it. A peak or a dip is a change from everything around it.
    const rest = complete.filter((index) => (moment.kind === 'shift' ? index < start : !inWindow(index)))
    if (!window.length || !rest.length) {
        return []
    }

    const change = moment.direction === 'up' ? 'rise' : 'fall'
    const drivers = results.breakdowns
        .map((breakdown) => driverOf(breakdown, window, rest, moment.direction))
        .filter((driver): driver is Driver => !!driver)
    const strong = drivers
        .filter(
            (driver) => driver.contribution >= MIN_CONTRIBUTION && driver.contribution - driver.usual >= MIN_SURPRISE
        )
        .sort((a, b) => b.contribution - b.usual - (a.contribution - a.usual))
        .slice(0, MAX_DRIVERS)

    const hosts = new Set(
        results.breakdowns
            .filter((breakdown) => breakdown.property.key === '$host')
            .flatMap((breakdown) => breakdown.rows.map((row) => siteOf(valueLabel(row.breakdown_value))))
    )
    const evidence: MomentEvidence[] = strong.map((driver) => ({
        text: `${mark('value', percent(driver.contribution))} of the ${change} ${driverPhrase(driver, hosts)}. ${
            driver.usual < 0.005
                ? 'It does not show up in the rest of the chart.'
                : `It is usually ${percent(driver.usual)} of the total.`
        }`,
        query: asViz(driver.query),
        driverShare: driver.contribution,
        driver: { key: driver.property.key, value: driver.value },
        cause: null,
    }))
    if (!strong.length && drivers.length) {
        const nouns = drivers.map((driver) => driver.property.noun)
        const list = nouns.length > 1 ? `${nouns.slice(0, -1).join(', ')} or ${nouns[nouns.length - 1]}` : nouns[0]
        evidence.push({
            text: `No single ${list} explains the ${change}. It happened across all of them at once${
                moment.direction === 'down' ? ', as it does when tracking stops' : ''
            }.`,
            query: null,
            driverShare: null,
            driver: null,
            cause: moment.direction === 'down' ? 'tracking' : null,
        })
    }

    const people = results.people ? peopleEvidence(moment, results.people, rest, context) : null
    return people ? [people, ...evidence] : evidence
}
