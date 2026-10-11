import {
    PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE,
    convertPropertyGroupToProperties,
} from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { formatDateTimeRange } from 'lib/utils/datetime'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { getDisplayNameFromEntityNode } from 'scenes/insights/utils'

import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'
import { BreakdownFilter, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import type { ActionsNode, EventsNode, FunnelsQuery } from '~/queries/schema/schema-general'
import { isGroupNode } from '~/queries/utils'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { BaseMathType, GroupMathType, HogQLMathType, PropertyMathType } from '~/types'

import { MathCategory, apiValueToMathType } from 'products/product_analytics/frontend/insights/trends/mathsLogic'
import type { MathDefinition } from 'products/product_analytics/frontend/insights/trends/mathsLogic'

import { describeFilter } from './filters/describeFilter'

export type SentenceSlot =
    | 'measure'
    | 'event'
    | 'seriesFilters'
    | 'moreSeries'
    | 'funnelActor'
    | 'funnelWindow'
    | 'formula'
    | 'split'
    | 'filters'
    | 'dateRange'
    | 'interval'
    | 'compare'
    | 'subscription'
    | 'alert'

export type SentencePart =
    | { type: 'text'; text: string }
    | {
          type: 'value'
          slot: SentenceSlot
          text: string
          seriesIndex?: number
          splitIndex?: number
          /** The subscription or alert the word stands for. Null when it stands for several. */
          itemId?: string | null
      }

export interface SentenceFollowUp {
    slot: 'subscription' | 'alert'
    /** The words before the value when it opens the line, and when it comes after another one. */
    opening: string
    lead: string
    text: string
    itemId: string | null
}

export interface Sentence {
    /** A line above the event lines. Empty unless the events are a numbered list of steps. */
    lead: SentencePart[]
    seriesLines: SentencePart[][]
    /** The whole sentence, or what follows the events when each event has a line of its own. */
    parts: SentencePart[]
    canCollapseSeries: boolean
}

/** From this many events, one sentence is too long to scan, so it names the first event and counts the others. */
const SERIES_COLLAPSE_FROM = 3

/** Past this many characters, two events read better on a line each than joined with "and". */
const SERIES_INLINE_MAX_LENGTH = 80

export interface SeriesFiltersPhrase {
    lead: string
    text: string
}

export interface SentenceSeries {
    measure: string
    /** The measure is an expression the person wrote, so its letters keep their case. */
    measureIsLiteral: boolean
    /** The word between the measure and its event: "total count of Pageview", "unique users doing Pageview". */
    link: string
    event: string
    filters: SeriesFiltersPhrase | null
}

export interface SentenceOptions {
    seriesExpanded: boolean
    /** An event whose first filter is being chosen, so its filter word shows before a filter exists. */
    pendingFilterSeriesIndex: number | null
    /** A formula is being written, so the formula word shows before a formula exists. */
    formulaPending: boolean
}

const PENDING_SERIES_FILTERS: SeriesFiltersPhrase = { lead: 'where', text: 'choose a filter' }
const PENDING_FORMULA = 'write a formula'

export function seriesLetter(seriesIndex: number): string {
    return String.fromCharCode(65 + (seriesIndex % 26))
}

export type FormulaStep = { type: 'series'; seriesIndex: number } | { type: 'words'; text: string }

const OPERATOR_WORDS: Record<string, string> = { '+': 'plus', '-': 'minus', '*': 'times', '/': 'divided by' }

/** A formula as words between the events, or null when reading the words left to right would change its meaning. */
export function formulaInWords(formula: string, seriesCount: number): FormulaStep[] | null {
    const tokens = formula.toUpperCase().match(/[A-Z]|\d+(?:\.\d+)?|\S/g) ?? []
    if (tokens.length < 3 || tokens.length % 2 === 0) {
        return null
    }
    const steps: FormulaStep[] = []
    const used = new Set<number>()
    let words: string[] = []
    let pastAddition = false
    for (const [index, token] of tokens.entries()) {
        if (index % 2 === 1) {
            const addition = token === '+' || token === '-'
            if (!OPERATOR_WORDS[token] || (pastAddition && !addition)) {
                return null
            }
            pastAddition = addition
            words.push(OPERATOR_WORDS[token])
        } else if (/^\d/.test(token)) {
            words.push(token)
        } else {
            const seriesIndex = token.charCodeAt(0) - 65
            if (!/^[A-Z]$/.test(token) || seriesIndex >= seriesCount || used.has(seriesIndex)) {
                return null
            }
            used.add(seriesIndex)
            if (words.length) {
                steps.push({ type: 'words', text: words.join(' ') })
                words = []
            }
            steps.push({ type: 'series', seriesIndex })
        }
    }
    if (words.length) {
        steps.push({ type: 'words', text: words.join(' ') })
    }
    return used.size > 0 && used.size === seriesCount ? steps : null
}

export interface DateRangePhrase {
    lead: string
    text: string
}

export type FunnelView = 'steps' | 'trends' | 'time_to_convert'

export interface FunnelSentenceDetails {
    actor: string
    window: string
    view: FunnelView
    anyOrder: boolean
}

export interface SentenceInput {
    funnel: FunnelSentenceDetails | null
    series: SentenceSeries[]
    formulas: string[]
    formulaInWords: FormulaStep[] | null
    splits: string[]
    filterCount: number
    dateRange: DateRangePhrase
    interval: string
    comparing: boolean
}

type TrendsSeriesNode = TrendsQuery['series'][number]
type SeriesNode = TrendsSeriesNode | FunnelsQuery['series'][number]
type MathDefinitions = Partial<Record<string, MathDefinition>>

const DEFAULT_DATE_RANGE_LABEL = 'Last 7 days'
const ABSOLUTE_DATE = /^\d{4}-\d{2}-\d{2}/
const TIMED_DATE = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/

function lowerFirst(text: string): string {
    return text.charAt(0).toLowerCase() + text.slice(1)
}

export function dateRangePhrase(label: string): DateRangePhrase {
    if (label === 'Today' || label === 'Yesterday') {
        return { lead: '', text: lowerFirst(label) }
    }
    if (label === 'All time' || label.startsWith('This ')) {
        return { lead: 'over', text: lowerFirst(label) }
    }
    if (label.startsWith('Last ') || label.startsWith('Previous ') || label === 'Year to date') {
        return { lead: 'over the', text: lowerFirst(label) }
    }
    const [from, to] = label.split(/\s[-–]\s/)
    if (from && to) {
        return { lead: 'from', text: `${from} to ${to}` }
    }
    return { lead: 'over', text: label }
}

function dateRangeLabel(dateFrom: string | null | undefined, dateTo: string | null | undefined): string {
    // Fixed dates read better formatted. A relative range keeps its name, such as "Last 30 days".
    const fixedRange = ABSOLUTE_DATE.test(dateFrom ?? '') && ABSOLUTE_DATE.test(dateTo ?? '')
    if (fixedRange && (TIMED_DATE.test(dateFrom ?? '') || TIMED_DATE.test(dateTo ?? ''))) {
        // A range zoomed into on the chart ends one second before a round time, and the round time reads better.
        const end = dayjs(dateTo)
        return formatDateTimeRange(dayjs(dateFrom), end.second() === 59 ? end.add(1, 'second') : end)
    }
    return (
        dateFilterToText(dateFrom, dateTo, DEFAULT_DATE_RANGE_LABEL, undefined, fixedRange) ?? DEFAULT_DATE_RANGE_LABEL
    )
}

function measureLink(node: TrendsSeriesNode, mathDefinitions: MathDefinitions): string {
    const category = mathDefinitions[apiValueToMathType(node.math, node.math_group_type_index)]?.category
    if (category === MathCategory.ActorCount || node.math === BaseMathType.FirstTimeForUser) {
        return 'doing'
    }
    return category === MathCategory.SessionCount ? 'with' : 'of'
}

function measureLabel(node: TrendsSeriesNode, mathDefinitions: MathDefinitions): string {
    if (node.math === HogQLMathType.HogQL) {
        return node.math_hogql?.trim() || 'SQL expression'
    }
    if (node.math === BaseMathType.FirstTimeForUser) {
        return 'first-time users'
    }
    const mathType = apiValueToMathType(node.math, node.math_group_type_index)
    const definition = mathDefinitions[mathType]
    if (!definition) {
        return mathType
    }
    if (mathType.startsWith(`${GroupMathType.UniqueGroup}::`)) {
        return `unique ${definition.name}`
    }
    const name = lowerFirst(definition.name)
    if (definition.category === MathCategory.PropertyValue) {
        const property =
            CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties[node.math_property as string]?.label ||
            node.math_property ||
            'property'
        return node.math === PropertyMathType.Sum ? `total ${property}` : `${name} ${property}`
    }
    if (definition.category === MathCategory.EventCountPerActor) {
        return `${name} count per user`
    }
    return name
}

function splitLabel(property: string | number, type: string | null | undefined): string {
    if (typeof property !== 'string') {
        return String(property)
    }
    const group = type
        ? PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[
              type as keyof typeof PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE
          ]
        : undefined
    return (group && getCoreFilterDefinition(property, group)?.label) || extractDisplayLabel(property)
}

function splitLabels(breakdownFilter: BreakdownFilter | null | undefined): string[] {
    if (!breakdownFilter) {
        return []
    }
    if (breakdownFilter.breakdowns?.length) {
        return breakdownFilter.breakdowns.map((breakdown) => splitLabel(breakdown.property, breakdown.type))
    }
    const { breakdown, breakdown_type } = breakdownFilter
    if (breakdown == null) {
        return []
    }
    if (breakdown_type === 'cohort') {
        return ['cohort']
    }
    const values = Array.isArray(breakdown) ? breakdown : [breakdown]
    return values.map((value) => splitLabel(value, breakdown_type))
}

interface QueryFormula {
    formula: string
    customName: string | null
}

function queryFormulas(query: TrendsQuery): QueryFormula[] {
    const trendsFilter = query.trendsFilter
    const fromNodes = (trendsFilter?.formulaNodes ?? []).flatMap((node) => {
        const formula = node.formula?.trim() ?? ''
        const customName = node.custom_name?.trim() || null
        return formula || customName ? [{ formula, customName }] : []
    })
    if (fromNodes.length) {
        return fromNodes
    }
    const formulas = trendsFilter?.formulas?.length ? trendsFilter.formulas : [trendsFilter?.formula ?? '']
    return formulas.filter(Boolean).map((formula) => ({ formula, customName: null }))
}

function queryFormulaInWords(formulas: QueryFormula[], seriesCount: number): FormulaStep[] | null {
    // A formula with a name shows that name, and several formulas cannot share one sentence.
    return formulas.length === 1 && !formulas[0].customName ? formulaInWords(formulas[0].formula, seriesCount) : null
}

function eventLabel(node: SeriesNode): string {
    const customName = node.custom_name?.trim()
    if (customName) {
        return customName
    }
    // Events counted together read as alternatives: "Pageview or Screen".
    if (isGroupNode(node) && node.nodes.length) {
        return node.nodes.map((inner) => getDisplayNameFromEntityNode(inner, false) || 'All events').join(' or ')
    }
    return getDisplayNameFromEntityNode(node as TrendsSeriesNode) || 'All events'
}

function seriesFiltersPhrase(node: SeriesNode): SeriesFiltersPhrase | null {
    const filters = node.properties ?? []
    if (!filters.length) {
        return null
    }
    // One filter fits in the sentence in words. More would make it too long to scan, so they are counted.
    return filters.length === 1
        ? { lead: 'where', text: describeFilter(filters[0]) }
        : { lead: 'with', text: `${filters.length} filters` }
}

function funnelWindowLabel(query: FunnelsQuery): string {
    const count = query.funnelsFilter?.funnelWindowInterval ?? 14
    const unit = query.funnelsFilter?.funnelWindowIntervalUnit ?? 'day'
    return `${count} ${unit}${count === 1 ? '' : 's'}`
}

function funnelActorLabel(query: FunnelsQuery, mathDefinitions: MathDefinitions): string {
    if (query.funnelsFilter?.funnelAggregateByHogQL) {
        return 'custom groups'
    }
    if (query.aggregation_group_type_index != null) {
        return mathDefinitions[`${GroupMathType.UniqueGroup}::${query.aggregation_group_type_index}`]?.name ?? 'groups'
    }
    return 'users'
}

function funnelView(query: FunnelsQuery): FunnelView {
    const vizType = query.funnelsFilter?.funnelVizType
    return vizType === 'trends' || vizType === 'time_to_convert' ? vizType : 'steps'
}

export function funnelSentenceInputFromQuery(query: FunnelsQuery, mathDefinitions: MathDefinitions): SentenceInput {
    return {
        funnel: {
            actor: funnelActorLabel(query, mathDefinitions),
            window: funnelWindowLabel(query),
            view: funnelView(query),
            anyOrder: query.funnelsFilter?.funnelOrderType === 'unordered',
        },
        series: query.series.map((node) => ({
            measure: '',
            measureIsLiteral: false,
            link: '',
            event: eventLabel(node),
            filters: seriesFiltersPhrase(node),
        })),
        formulas: [],
        formulaInWords: null,
        splits: splitLabels(query.breakdownFilter),
        filterCount: convertPropertyGroupToProperties(query.properties)?.length ?? 0,
        dateRange: dateRangePhrase(dateRangeLabel(query.dateRange?.date_from, query.dateRange?.date_to)),
        interval: query.interval ?? 'day',
        comparing: !!query.compareFilter?.compare,
    }
}

export function sentenceInputFromQuery(query: TrendsQuery, mathDefinitions: MathDefinitions): SentenceInput {
    const formulas = queryFormulas(query)
    return {
        funnel: null,
        series: query.series.map((node) => ({
            measure: measureLabel(node, mathDefinitions),
            measureIsLiteral: node.math === HogQLMathType.HogQL && !!node.math_hogql?.trim(),
            link: measureLink(node, mathDefinitions),
            event: eventLabel(node),
            filters: seriesFiltersPhrase(node),
        })),
        formulas: formulas.map(({ formula, customName }) => customName ?? formula),
        formulaInWords: queryFormulaInWords(formulas, query.series.length),
        splits: splitLabels(query.breakdownFilter),
        filterCount: convertPropertyGroupToProperties(query.properties)?.length ?? 0,
        dateRange: dateRangePhrase(dateRangeLabel(query.dateRange?.date_from, query.dateRange?.date_to)),
        interval: query.interval ?? 'day',
        comparing: !!query.compareFilter?.compare,
    }
}

export function seriesEventParts(
    series: SentenceSeries,
    seriesIndex: number,
    options: SentenceOptions
): SentencePart[] {
    const parts: SentencePart[] = [{ type: 'value', slot: 'event', text: series.event, seriesIndex }]
    const filters = series.filters ?? (options.pendingFilterSeriesIndex === seriesIndex ? PENDING_SERIES_FILTERS : null)
    if (filters) {
        parts.push({ type: 'text', text: ` ${filters.lead} ` })
        parts.push({ type: 'value', slot: 'seriesFilters', text: filters.text, seriesIndex })
    }
    return parts
}

function seriesParts(
    series: SentenceSeries,
    seriesIndex: number,
    startsLine: boolean,
    input: SentenceInput,
    options: SentenceOptions
): SentencePart[] {
    const parts: SentencePart[] = [
        {
            type: 'value',
            slot: 'measure',
            text: startsLine && !series.measureIsLiteral ? capitalizeFirstLetter(series.measure) : series.measure,
            seriesIndex,
        },
        { type: 'text', text: ` ${series.link} ` },
        ...seriesEventParts(series, seriesIndex, options),
    ]
    if (input.formulas.length && !input.formulaInWords) {
        parts.push({ type: 'text', text: ` (${seriesLetter(seriesIndex)})` })
    }
    return parts
}

/** One group for each event, in the order the formula names them. The formula's words open or close a group. */
function formulaSeriesGroups(steps: FormulaStep[], input: SentenceInput, options: SentenceOptions): SentencePart[][] {
    const groups: SentencePart[][] = []
    let opening: SentencePart[] = []
    steps.forEach((step, index) => {
        if (step.type === 'series') {
            const startsLine = !groups.length && !opening.length
            groups.push([
                ...opening,
                ...seriesParts(input.series[step.seriesIndex], step.seriesIndex, startsLine, input, options),
            ])
            opening = []
            return
        }
        const word: SentencePart = { type: 'value', slot: 'formula', text: step.text }
        if (index === steps.length - 1) {
            groups[groups.length - 1].push({ type: 'text', text: ' ' }, word)
        } else {
            opening = [word, { type: 'text', text: ' ' }]
        }
    })
    return groups
}

/** What follows the events. It always starts with a text part that opens with a comma. */
export function partsAfterSeries(input: SentenceInput, options: SentenceOptions): SentencePart[] {
    const parts: SentencePart[] = []
    const text = (value: string): void => {
        parts.push({ type: 'text', text: value })
    }

    if (input.funnel) {
        text(', within ')
        parts.push({ type: 'value', slot: 'funnelWindow', text: input.funnel.window })
    }
    if ((input.formulas.length && !input.formulaInWords) || options.formulaPending) {
        text(', combined as ')
        parts.push({
            type: 'value',
            slot: 'formula',
            text: input.formulas.length ? input.formulas.join(', ') : PENDING_FORMULA,
        })
    }
    input.splits.forEach((split, splitIndex) => {
        text(splitIndex === 0 ? ', split by ' : ' and ')
        parts.push({ type: 'value', slot: 'split', text: split, splitIndex })
    })
    if (input.filterCount) {
        text(', with ')
        parts.push({
            type: 'value',
            slot: 'filters',
            text: input.filterCount === 1 ? '1 filter' : `${input.filterCount} filters`,
        })
    }
    text(input.dateRange.lead ? `, ${input.dateRange.lead} ` : ', ')
    parts.push({ type: 'value', slot: 'dateRange', text: input.dateRange.text })
    // A funnel has one result for the whole range, unless it shows conversion over time.
    if (!input.funnel || input.funnel.view === 'trends') {
        text(' by ')
        parts.push({ type: 'value', slot: 'interval', text: input.interval })
    }
    if (input.comparing) {
        text(', compared to the ')
        parts.push({ type: 'value', slot: 'compare', text: 'previous period' })
    }
    text('.')

    return parts
}

/** The parts after the events for when the events have lines of their own: the comma is already on the line above. */
export function withoutLeadingComma([first, ...rest]: SentencePart[]): SentencePart[] {
    const lead = first.text.replace(/^, /, '')
    return lead ? [{ ...first, text: lead }, ...rest] : rest
}

/** The parts grouped into clauses, with each comma moved to the end of the clause before it. */
export function sentenceClauses(parts: SentencePart[]): SentencePart[][] {
    const clauses: SentencePart[][] = [[]]
    for (const [index, part] of parts.entries()) {
        const current = clauses[clauses.length - 1]
        const next = parts[index + 1]
        if (part.type === 'text' && part.text.startsWith(', ') && current.length) {
            current.push({ type: 'text', text: ',' })
            clauses.push([{ type: 'text', text: part.text.slice(2) }])
        } else if (part.type === 'text' && part.text === ' and ' && current.length) {
            clauses.push([{ type: 'text', text: 'and ' }])
        } else if (part.type === 'text' && part.text === ' ' && next?.type === 'value' && next.slot === 'formula') {
            // A formula's words join two events the way "and" does, so they open a clause too.
            clauses.push([])
        } else {
            current.push(part)
        }
    }
    return clauses
}

export function seriesLabel(series: SentenceSeries): string {
    const measure = series.measureIsLiteral ? series.measure : capitalizeFirstLetter(series.measure)
    return `${measure} ${series.link} ${series.event}`
}

export function collapsedSeries(input: SentenceInput): SentenceSeries[] {
    return !input.funnel && input.series.length >= SERIES_COLLAPSE_FROM ? input.series.slice(1) : []
}

function textLength(parts: SentencePart[]): number {
    return parts.reduce((length, part) => length + part.text.length, 0)
}

export function buildSentence(input: SentenceInput, options: SentenceOptions): Sentence {
    const afterSeries = partsAfterSeries(input, options)
    const hidden = collapsedSeries(input)
    const inWords = input.formulaInWords
    const groups = inWords
        ? formulaSeriesGroups(inWords, input, options)
        : input.series.map((series, seriesIndex) => seriesParts(series, seriesIndex, seriesIndex === 0, input, options))
    const lastGroup = groups.length - 1
    // The lines still read as one sentence: a comma ends each event, and "and" opens the last one.
    // A formula in words already joins the events, so only the last line takes a comma.
    const seriesLines = (): SentencePart[][] =>
        groups.map((group, index) => [
            ...(!inWords && index > 0 && index === lastGroup ? [{ type: 'text' as const, text: 'and ' }] : []),
            ...group,
            ...(!inWords || index === lastGroup ? [{ type: 'text' as const, text: ',' }] : []),
        ])

    if (hidden.length) {
        // A formula or a filter being chosen points at one event, so every event has to be on screen.
        const needsEveryEvent = input.formulas.length > 0 || (options.pendingFilterSeriesIndex ?? 0) > 0
        if (needsEveryEvent || options.seriesExpanded) {
            return {
                lead: [],
                seriesLines: seriesLines(),
                parts: withoutLeadingComma(afterSeries),
                canCollapseSeries: !needsEveryEvent,
            }
        }
        return {
            lead: [],
            seriesLines: [],
            parts: [
                ...seriesParts(input.series[0], 0, true, input, options),
                { type: 'text', text: ' and ' },
                { type: 'value', slot: 'moreSeries', text: `${hidden.length} more` },
                ...afterSeries,
            ],
            canCollapseSeries: false,
        }
    }

    const series = groups.flatMap((group, index): SentencePart[] => [
        ...(index > 0 ? [{ type: 'text' as const, text: inWords ? ' ' : ' and ' }] : []),
        ...group,
    ])
    if (input.series.length > 1 && textLength(series) > SERIES_INLINE_MAX_LENGTH) {
        return {
            lead: [],
            seriesLines: seriesLines(),
            parts: withoutLeadingComma(afterSeries),
            canCollapseSeries: false,
        }
    }
    return { lead: [], seriesLines: [], parts: [...series, ...afterSeries], canCollapseSeries: false }
}

export function seriesNodeFromPick(
    groupType: TaxonomicFilterGroupType,
    value: string | number | null,
    name: string | undefined,
    previous?: SeriesNode
): EventsNode | ActionsNode | null {
    const carried = previous
        ? {
              math: previous.math,
              math_property: previous.math_property,
              math_property_type: previous.math_property_type,
              math_hogql: previous.math_hogql,
              math_group_type_index: previous.math_group_type_index,
              math_multiplier: previous.math_multiplier,
              properties: previous.properties,
          }
        : {}
    if (groupType === TaxonomicFilterGroupType.Actions) {
        const id = Number(value)
        return Number.isFinite(id) ? { ...carried, kind: NodeKind.ActionsNode, id, name: name ?? String(value) } : null
    }
    if (groupType === TaxonomicFilterGroupType.Events) {
        const event = value == null ? null : String(value)
        return { ...carried, kind: NodeKind.EventsNode, event, name: name ?? event ?? 'All events' }
    }
    return null
}
