/**
 * PromQL autocomplete, modeled on Grafana's Prometheus query field.
 *
 * The text before the cursor gives a "situation" (at the start of an expression, inside a
 * function, in a label selector before or after a label name, in a `by (…)` grouping, or in a
 * range). Each situation has its own suggestions: functions and metric names, label names,
 * label values, or durations. The text does not need to parse: the user is still typing it.
 */

import type { PromQLCompletionItem } from 'lib/monaco/languages/promqlCompletionRegistry'

import { printLabelName } from './promqlPrinter'

export interface PromQLLabelMatcher {
    label: string
    op: string
    value: string
}

export type PromQLSituation =
    | { type: 'EMPTY' }
    | { type: 'AT_ROOT' }
    | { type: 'IN_FUNCTION' }
    | { type: 'IN_DURATION' }
    | { type: 'IN_GROUPING'; metricName?: string; usedLabels: string[] }
    | { type: 'IN_QUOTED_METRIC_NAME' }
    | { type: 'IN_LABEL_SELECTOR_NO_LABEL_NAME'; metricName?: string; otherLabels: PromQLLabelMatcher[] }
    | {
          type: 'IN_LABEL_SELECTOR_WITH_LABEL_NAME'
          metricName?: string
          labelName: string
          op: string
          betweenQuotes: boolean
          otherLabels: PromQLLabelMatcher[]
      }

export type PromQLCompletion = PromQLCompletionItem

export interface PromQLMetricName {
    name: string
    /** OTel type, e.g. gauge, sum, histogram. */
    type?: string
}

/** Where suggestions come from. Each call can fail or be slow; a failure gives no suggestions. */
export interface PromQLCompletionSource {
    metricNames: (search: string) => Promise<PromQLMetricName[]>
    labelNames: (metricName: string | undefined, search: string) => Promise<string[]>
    labelValues: (labelName: string, metricName: string | undefined, search: string) => Promise<string[]>
    /** Whether the last metric names came from a search on the server, so typing more must ask again. */
    metricNamesSearchedOnServer?: () => boolean
}

export interface PromQLCompletionResult {
    /** Offset where the text the suggestions replace starts; the end is the cursor. */
    from: number
    items: PromQLCompletion[]
    /** The list was searched on the server for the typed word, so typing more must ask again. */
    incomplete: boolean
}

// --- Function and aggregation catalog -------------------------------------------------------

interface CatalogEntry {
    signature: string
    documentation: string
}

export const PROMQL_AGGREGATIONS: Record<string, CatalogEntry> = {
    sum: { signature: 'sum by (labels) (v)', documentation: 'Adds the values of the series in each group.' },
    avg: { signature: 'avg by (labels) (v)', documentation: 'Calculates the average of the series in each group.' },
    min: { signature: 'min by (labels) (v)', documentation: 'Selects the lowest value in each group.' },
    max: { signature: 'max by (labels) (v)', documentation: 'Selects the highest value in each group.' },
    count: { signature: 'count by (labels) (v)', documentation: 'Counts the series in each group.' },
    group: { signature: 'group by (labels) (v)', documentation: 'Gives 1 for each group.' },
    stddev: { signature: 'stddev by (labels) (v)', documentation: 'Calculates the population standard deviation.' },
    stdvar: { signature: 'stdvar by (labels) (v)', documentation: 'Calculates the population variance.' },
    quantile: {
        signature: 'quantile by (labels) (φ, v)',
        documentation: 'Calculates the φ-quantile (0 ≤ φ ≤ 1) of the series values in each group.',
    },
    median: { signature: 'median by (labels) (v)', documentation: 'Calculates the median of the series values.' },
    topk: { signature: 'topk(k, v)', documentation: 'Keeps the k series with the highest values.' },
    bottomk: { signature: 'bottomk(k, v)', documentation: 'Keeps the k series with the lowest values.' },
    count_values: {
        signature: 'count_values("label", v)',
        documentation: 'Counts the series that have each value, and puts the value in a label.',
    },
    limitk: { signature: 'limitk(k, v)', documentation: 'Keeps k series from each group.' },
    limit_ratio: { signature: 'limit_ratio(r, v)', documentation: 'Keeps about the ratio r of the series.' },
}

export const PROMQL_FUNCTIONS: Record<string, CatalogEntry> = {
    rate: {
        signature: 'rate(v range-vector)',
        documentation:
            'Per-second rate of increase of a counter. Leave out the range, as in rate(x), to use the chart interval.',
    },
    increase: {
        signature: 'increase(v range-vector)',
        documentation: 'Increase of a counter in the range. Counter resets are handled.',
    },
    irate: {
        signature: 'irate(v range-vector)',
        documentation: 'Per-second rate from the last two samples in the range.',
    },
    delta: {
        signature: 'delta(v range-vector)',
        documentation: 'Difference between the first and last value of a gauge.',
    },
    idelta: {
        signature: 'idelta(v range-vector)',
        documentation: 'Difference between the last two samples of a gauge.',
    },
    deriv: {
        signature: 'deriv(v range-vector)',
        documentation: 'Per-second derivative of a gauge (linear regression).',
    },
    changes: { signature: 'changes(v range-vector)', documentation: 'Number of times the value changed in the range.' },
    resets: { signature: 'resets(v range-vector)', documentation: 'Number of counter resets in the range.' },
    predict_linear: {
        signature: 'predict_linear(v range-vector, t scalar)',
        documentation: 'Predicts the value t seconds from now (linear regression).',
    },
    histogram_quantile: {
        signature: 'histogram_quantile(φ scalar, b instant-vector)',
        documentation:
            'Calculates the φ-quantile from histogram buckets, for example histogram_quantile(0.95, sum by (le) (rate(x_bucket))).',
    },
    histogram_quantiles: {
        signature: 'histogram_quantiles("label", φ1, φ2, …, b)',
        documentation: 'Calculates several quantiles at once and puts each quantile in a label.',
    },
    histogram_count: { signature: 'histogram_count(v)', documentation: 'Observation count of a native histogram.' },
    histogram_sum: { signature: 'histogram_sum(v)', documentation: 'Sum of observations of a native histogram.' },
    histogram_avg: { signature: 'histogram_avg(v)', documentation: 'Average observation of a native histogram.' },
    histogram_fraction: {
        signature: 'histogram_fraction(lower, upper, b)',
        documentation: 'Fraction of observations between lower and upper.',
    },
    avg_over_time: { signature: 'avg_over_time(v range-vector)', documentation: 'Average value in the range.' },
    min_over_time: { signature: 'min_over_time(v range-vector)', documentation: 'Lowest value in the range.' },
    max_over_time: { signature: 'max_over_time(v range-vector)', documentation: 'Highest value in the range.' },
    sum_over_time: { signature: 'sum_over_time(v range-vector)', documentation: 'Sum of the values in the range.' },
    count_over_time: { signature: 'count_over_time(v range-vector)', documentation: 'Number of samples in the range.' },
    last_over_time: { signature: 'last_over_time(v range-vector)', documentation: 'Last value in the range.' },
    present_over_time: {
        signature: 'present_over_time(v range-vector)',
        documentation: 'Gives 1 for a series with samples.',
    },
    quantile_over_time: {
        signature: 'quantile_over_time(φ scalar, v range-vector)',
        documentation: 'φ-quantile of the values in the range.',
    },
    stddev_over_time: {
        signature: 'stddev_over_time(v range-vector)',
        documentation: 'Standard deviation in the range.',
    },
    stdvar_over_time: { signature: 'stdvar_over_time(v range-vector)', documentation: 'Variance in the range.' },
    absent: { signature: 'absent(v instant-vector)', documentation: 'Gives 1 when the vector has no series.' },
    absent_over_time: {
        signature: 'absent_over_time(v range-vector)',
        documentation: 'Gives 1 when the range has no samples.',
    },
    abs: { signature: 'abs(v)', documentation: 'Absolute value.' },
    ceil: { signature: 'ceil(v)', documentation: 'Rounds up to the nearest integer.' },
    floor: { signature: 'floor(v)', documentation: 'Rounds down to the nearest integer.' },
    round: { signature: 'round(v, to_nearest=1)', documentation: 'Rounds to the nearest multiple of to_nearest.' },
    clamp: { signature: 'clamp(v, min, max)', documentation: 'Limits the values to the range min to max.' },
    clamp_min: { signature: 'clamp_min(v, min)', documentation: 'Limits the values to a lower bound.' },
    clamp_max: { signature: 'clamp_max(v, max)', documentation: 'Limits the values to an upper bound.' },
    sqrt: { signature: 'sqrt(v)', documentation: 'Square root.' },
    exp: { signature: 'exp(v)', documentation: 'Exponential function.' },
    ln: { signature: 'ln(v)', documentation: 'Natural logarithm.' },
    log2: { signature: 'log2(v)', documentation: 'Binary logarithm.' },
    log10: { signature: 'log10(v)', documentation: 'Decimal logarithm.' },
    sgn: { signature: 'sgn(v)', documentation: 'Sign of the value: 1, 0 or -1.' },
    scalar: { signature: 'scalar(v)', documentation: 'Changes a one-series vector to a scalar.' },
    vector: { signature: 'vector(s scalar)', documentation: 'Changes a scalar to a vector with no labels.' },
    sort: { signature: 'sort(v)', documentation: 'Sorts by value, lowest first (instant queries only).' },
    sort_desc: { signature: 'sort_desc(v)', documentation: 'Sorts by value, highest first (instant queries only).' },
    label_replace: {
        signature: 'label_replace(v, "dst", "replacement", "src", "regex")',
        documentation: 'Sets a label from a regex match on another label.',
    },
    label_join: {
        signature: 'label_join(v, "dst", "separator", "src1", …)',
        documentation: 'Sets a label to the joined values of other labels.',
    },
    timestamp: { signature: 'timestamp(v)', documentation: 'Timestamp of each sample, in seconds.' },
    time: { signature: 'time()', documentation: 'Evaluation time, in seconds since the epoch.' },
    running_sum: {
        signature: 'running_sum(v)',
        documentation: 'Adds the values of each series from the start of the range.',
    },
}

const GROUPING_KEYWORDS = new Set(['by', 'without', 'on', 'ignoring', 'group_left', 'group_right'])

export const PROMQL_DURATIONS: [string, string][] = [
    ['$__rate_interval', 'The chart interval, as an omitted range'],
    ['$__interval', 'The chart interval'],
    ['1m', '1 minute'],
    ['5m', '5 minutes'],
    ['10m', '10 minutes'],
    ['30m', '30 minutes'],
    ['1h', '1 hour'],
    ['6h', '6 hours'],
    ['1d', '1 day'],
    ['1w', '1 week'],
]

// --- Situation detection --------------------------------------------------------------------

type TokenType = 'ident' | 'string' | 'number' | 'op' | 'open' | 'close'

interface Token {
    type: TokenType
    value: string
    /** True for a string that the text ends inside. */
    unterminated?: boolean
}

const IDENT_CHAR = /[A-Za-z0-9_:.]/
const IDENT_START = /[A-Za-z_]/

function tokenize(text: string): Token[] {
    const tokens: Token[] = []
    let i = 0
    while (i < text.length) {
        const ch = text[i]
        if (/\s/.test(ch)) {
            i++
        } else if (ch === '#') {
            while (i < text.length && text[i] !== '\n') {
                i++
            }
        } else if (ch === '"' || ch === "'" || ch === '`') {
            let value = ''
            let j = i + 1
            while (j < text.length && text[j] !== ch) {
                if (text[j] === '\\' && ch !== '`' && j + 1 < text.length) {
                    value += text[j + 1]
                    j += 2
                    continue
                }
                value += text[j]
                j++
            }
            tokens.push({ type: 'string', value, ...(j >= text.length ? { unterminated: true } : {}) })
            i = j + 1
        } else if (IDENT_START.test(ch) || ch === '$') {
            let j = i + 1
            while (j < text.length && IDENT_CHAR.test(text[j])) {
                j++
            }
            tokens.push({ type: 'ident', value: text.slice(i, j) })
            i = j
        } else if (/[0-9.]/.test(ch)) {
            let j = i + 1
            while (j < text.length && /[0-9a-zA-Z.]/.test(text[j])) {
                j++
            }
            tokens.push({ type: 'number', value: text.slice(i, j) })
            i = j
        } else if ('({['.includes(ch)) {
            tokens.push({ type: 'open', value: ch })
            i++
        } else if (')}]'.includes(ch)) {
            tokens.push({ type: 'close', value: ch })
            i++
        } else {
            const op = ['=~', '!~', '!=', '==', '>=', '<='].find((candidate) => text.startsWith(candidate, i)) ?? ch
            tokens.push({ type: 'op', value: op })
            i += op.length
        }
    }
    return tokens
}

interface Frame {
    open: '(' | '{' | '['
    /** Index of the open token. */
    start: number
    grouping: boolean
}

/** Frames still open at the end of the tokens, innermost last. */
function openFrames(tokens: Token[]): Frame[] {
    const frames: Frame[] = []
    tokens.forEach((token, index) => {
        if (token.type === 'open') {
            const previous = tokens[index - 1]
            frames.push({
                open: token.value as Frame['open'],
                start: index,
                grouping:
                    token.value === '(' &&
                    previous?.type === 'ident' &&
                    GROUPING_KEYWORDS.has(previous.value.toLowerCase()),
            })
        } else if (token.type === 'close') {
            frames.pop()
        }
    })
    return frames
}

/** The metric a selector reads: the name before `{`, a leading quoted name, or `__name__="x"`. */
function selectorMetricName(tokens: Token[], braceIndex: number, inside: Token[]): string | undefined {
    const before = tokens[braceIndex - 1]
    if (before?.type === 'ident' && !GROUPING_KEYWORDS.has(before.value) && !before.value.startsWith('$')) {
        return before.value
    }
    if (inside[0]?.type === 'string' && !inside[0].unterminated && (inside[1] === undefined || isComma(inside[1]))) {
        return inside[0].value
    }
    for (let i = 0; i + 2 < inside.length; i++) {
        if (inside[i].type === 'ident' && inside[i].value === '__name__' && inside[i + 1].value === '=') {
            return inside[i + 2].value
        }
    }
    return undefined
}

const isComma = (token: Token): boolean => token.type === 'op' && token.value === ','
const MATCH_OPS = new Set(['=', '!=', '=~', '!~'])

function splitSegments(tokens: Token[]): Token[][] {
    const segments: Token[][] = [[]]
    for (const token of tokens) {
        if (isComma(token)) {
            segments.push([])
        } else {
            segments[segments.length - 1].push(token)
        }
    }
    return segments
}

function completeMatchers(segments: Token[][]): PromQLLabelMatcher[] {
    return segments
        .filter(
            (segment) =>
                segment.length === 3 &&
                (segment[0].type === 'ident' || segment[0].type === 'string') &&
                MATCH_OPS.has(segment[1].value) &&
                segment[2].type === 'string' &&
                !segment[2].unterminated &&
                segment[0].value !== '__name__'
        )
        .map((segment) => ({ label: segment[0].value, op: segment[1].value, value: segment[2].value }))
}

/** The metric name nearest to token `index`. Used to scope label suggestions in a grouping. */
function nearestMetricName(tokens: Token[], index: number): string | undefined {
    const candidates: { name: string; distance: number }[] = []
    const stack: { grouping: boolean; brace: boolean }[] = []
    tokens.forEach((token, i) => {
        const next = tokens[i + 1]
        if (token.type === 'open') {
            const previous = tokens[i - 1]
            stack.push({
                grouping: token.value === '(' && previous?.type === 'ident' && GROUPING_KEYWORDS.has(previous.value),
                brace: token.value === '{',
            })
            if (token.value === '{') {
                const end = tokens.findIndex((t, j) => j > i && t.type === 'close' && t.value === '}')
                const name = selectorMetricName(tokens, i, tokens.slice(i + 1, end === -1 ? undefined : end))
                if (name) {
                    candidates.push({ name, distance: Math.abs(i - index) })
                }
            }
            return
        }
        if (token.type === 'close') {
            stack.pop()
            return
        }
        const frame = stack[stack.length - 1]
        const isCall = next?.type === 'open' && next.value === '('
        // `sum by (…)` puts the grouping between the name and its parenthesis.
        const isKeyword =
            GROUPING_KEYWORDS.has(token.value) ||
            ['and', 'or', 'unless', 'offset', 'bool'].includes(token.value) ||
            token.value in PROMQL_AGGREGATIONS ||
            token.value in PROMQL_FUNCTIONS
        const beforeBrace = next?.type === 'open' && next.value === '{'
        if (
            token.type === 'ident' &&
            !frame?.grouping &&
            !frame?.brace &&
            !isCall &&
            !isKeyword &&
            !beforeBrace &&
            !token.value.startsWith('$')
        ) {
            candidates.push({ name: token.value, distance: Math.abs(i - index) })
        }
    })
    return candidates.sort((a, b) => a.distance - b.distance)[0]?.name
}

/** The partial word the cursor is in: identifier characters before the cursor. */
function wordStart(text: string, offset: number): number {
    let start = offset
    while (start > 0 && IDENT_CHAR.test(text[start - 1])) {
        start--
    }
    if (start > 0 && text[start - 1] === '$') {
        start--
    }
    return start
}

/**
 * The situation at `offset` in `text`, and where the word being typed starts.
 * `text` can be the whole query; text after the cursor only helps to find the metric of a grouping.
 */
export function getSituation(text: string, offset: number): { situation: PromQLSituation; from: number } | null {
    const before = text.slice(0, offset)
    const tokens = tokenize(before)
    const last = tokens[tokens.length - 1]

    // Inside a quoted string: a label value, or a quoted metric name.
    if (last?.type === 'string' && last.unterminated) {
        const quoteAt = Math.max(before.lastIndexOf('"'), before.lastIndexOf("'"), before.lastIndexOf('`'))
        const from = quoteAt + 1
        const frames = openFrames(tokens)
        const frame = frames[frames.length - 1]
        if (frame?.open !== '{') {
            return null
        }
        const inside = tokens.slice(frame.start + 1)
        const segments = splitSegments(inside)
        const segment = segments[segments.length - 1]
        const metricName = selectorMetricName(tokens, frame.start, inside)
        if (segment.length === 3 && MATCH_OPS.has(segment[1].value)) {
            if (segment[0].value === '__name__') {
                return { situation: { type: 'IN_QUOTED_METRIC_NAME' }, from }
            }
            return {
                situation: {
                    type: 'IN_LABEL_SELECTOR_WITH_LABEL_NAME',
                    metricName,
                    labelName: segment[0].value,
                    op: segment[1].value,
                    betweenQuotes: true,
                    otherLabels: completeMatchers(segments.slice(0, -1)),
                },
                from,
            }
        }
        if (segment.length === 1 && segments.length === 1 && tokens[frame.start - 1]?.type !== 'ident') {
            return { situation: { type: 'IN_QUOTED_METRIC_NAME' }, from }
        }
        return null
    }

    const from = wordStart(before, offset)
    const context = tokenize(before.slice(0, from))
    const previous = context[context.length - 1]
    if (!context.length) {
        return { situation: before.trim() ? { type: 'AT_ROOT' } : { type: 'EMPTY' }, from }
    }

    const frames = openFrames(context)
    const frame = frames[frames.length - 1]

    if (frame?.open === '[') {
        const afterOpen = context.slice(frame.start + 1)
        const ok = afterOpen.length === 0 || (afterOpen.length === 2 && afterOpen[1].value === ':')
        return ok ? { situation: { type: 'IN_DURATION' }, from } : null
    }

    if (frame?.open === '{') {
        const inside = context.slice(frame.start + 1)
        const segments = splitSegments(inside)
        const segment = segments[segments.length - 1]
        const metricName = selectorMetricName(context, frame.start, inside)
        const otherLabels = completeMatchers(segments.slice(0, -1))
        if (segment.length === 0) {
            return { situation: { type: 'IN_LABEL_SELECTOR_NO_LABEL_NAME', metricName, otherLabels }, from }
        }
        if (segment.length === 2 && MATCH_OPS.has(segment[1].value)) {
            if (segment[0].value === '__name__') {
                return null
            }
            return {
                situation: {
                    type: 'IN_LABEL_SELECTOR_WITH_LABEL_NAME',
                    metricName,
                    labelName: segment[0].value,
                    op: segment[1].value,
                    betweenQuotes: false,
                    otherLabels,
                },
                from,
            }
        }
        return null
    }

    if (frame?.grouping) {
        const labels = context
            .slice(frame.start + 1)
            .filter((token) => token.type === 'ident' || token.type === 'string')
        const allTokens = tokenize(text)
        return {
            situation: {
                type: 'IN_GROUPING',
                metricName: nearestMetricName(allTokens, frame.start),
                usedLabels: labels.map((token) => token.value),
            },
            from,
        }
    }

    // Start of an expression: after an open paren, a comma, or an operator.
    const startsExpression =
        (previous.type === 'open' && previous.value === '(') ||
        isComma(previous) ||
        (previous.type === 'op' && !MATCH_OPS.has(previous.value)) ||
        (previous.type === 'ident' && ['and', 'or', 'unless'].includes(previous.value.toLowerCase()))
    if (startsExpression) {
        return { situation: frame?.open === '(' ? { type: 'IN_FUNCTION' } : { type: 'AT_ROOT' }, from }
    }
    return null
}

// --- Completions ----------------------------------------------------------------------------

const LEGACY_METRIC_NAME = /^[a-zA-Z_:][a-zA-Z0-9_:]*$/
const REGEX_SPECIAL = /[.*+?^${}()|[\]\\]/g

const escapeString = (value: string): string => value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')

const METRIC_TYPE_LABELS: Record<string, string> = {
    sum: 'counter',
    gauge: 'gauge',
    histogram: 'histogram',
    exponential_histogram: 'exponential histogram',
    summary: 'summary',
}

function catalogItems(): PromQLCompletion[] {
    const aggregations = Object.entries(PROMQL_AGGREGATIONS).map(
        ([name, entry]): PromQLCompletion => ({
            label: name,
            insertText: `${name}($0)`,
            kind: 'aggregation',
            detail: entry.signature,
            documentation: entry.documentation,
            snippet: true,
            retrigger: true,
            sortText: `2${name}`,
        })
    )
    const functions = Object.entries(PROMQL_FUNCTIONS).map(
        ([name, entry]): PromQLCompletion => ({
            label: name,
            insertText: `${name}($0)`,
            kind: 'function',
            detail: entry.signature,
            documentation: entry.documentation,
            snippet: true,
            retrigger: true,
            sortText: `3${name}`,
        })
    )
    return [...aggregations, ...functions]
}

/** Metric names as PromQL needs them: OTel names with dots go in the quoted selector form. */
function metricItems(metrics: PromQLMetricName[]): PromQLCompletion[] {
    const items: PromQLCompletion[] = []
    for (const metric of metrics) {
        const names = metric.type === 'histogram' ? [metric.name, `${metric.name}_bucket`] : [metric.name]
        for (const name of names) {
            const type = name.endsWith('_bucket') && name !== metric.name ? 'histogram buckets (le)' : metric.type
            items.push({
                label: name,
                insertText: LEGACY_METRIC_NAME.test(name) ? name : `{"${escapeString(name)}"}`,
                kind: 'metric',
                detail: type ? (METRIC_TYPE_LABELS[type] ?? type) : undefined,
                sortText: `1${name}`,
            })
        }
    }
    return items
}

const settle = async <T>(promise: Promise<T>, fallback: T): Promise<T> => {
    try {
        return await promise
    } catch {
        return fallback
    }
}

export async function getPromQLCompletions(
    text: string,
    offset: number,
    source: PromQLCompletionSource
): Promise<PromQLCompletionResult | null> {
    const found = getSituation(text, offset)
    if (!found) {
        return null
    }
    const { situation, from } = found
    const typed = text.slice(from, offset)

    switch (situation.type) {
        case 'EMPTY':
        case 'AT_ROOT':
        case 'IN_FUNCTION': {
            const metrics = await settle(source.metricNames(typed), [])
            return {
                from,
                items: [...metricItems(metrics), ...catalogItems()],
                incomplete: source.metricNamesSearchedOnServer?.() ?? true,
            }
        }
        case 'IN_QUOTED_METRIC_NAME': {
            const metrics = await settle(source.metricNames(typed), [])
            return {
                from,
                items: metrics.map((metric) => ({
                    label: metric.name,
                    insertText: escapeString(metric.name),
                    kind: 'metric',
                    detail: metric.type ? (METRIC_TYPE_LABELS[metric.type] ?? metric.type) : undefined,
                })),
                incomplete: source.metricNamesSearchedOnServer?.() ?? true,
            }
        }
        case 'IN_DURATION':
            return {
                from,
                items: PROMQL_DURATIONS.map(([value, detail], index) => ({
                    label: value,
                    insertText: value,
                    kind: 'duration',
                    detail,
                    sortText: String(index).padStart(2, '0'),
                })),
                incomplete: false,
            }
        case 'IN_GROUPING': {
            const labels = await settle(source.labelNames(situation.metricName, typed), [])
            return {
                from,
                items: labels
                    .filter((label) => !situation.usedLabels.includes(label))
                    .map((label) => ({ label, insertText: printLabelName(label), kind: 'label' })),
                incomplete: true,
            }
        }
        case 'IN_LABEL_SELECTOR_NO_LABEL_NAME': {
            const used = new Set(situation.otherLabels.map((matcher) => matcher.label))
            const labels = await settle(source.labelNames(situation.metricName, typed), [])
            return {
                from,
                items: labels
                    .filter((label) => !used.has(label))
                    .map((label) => ({
                        label,
                        insertText: `${printLabelName(label)}=`,
                        kind: 'label',
                        retrigger: true,
                    })),
                incomplete: true,
            }
        }
        case 'IN_LABEL_SELECTOR_WITH_LABEL_NAME': {
            const values = await settle(source.labelValues(situation.labelName, situation.metricName, typed), [])
            const isRegex = situation.op === '=~' || situation.op === '!~'
            return {
                from,
                items: values.map((value) => {
                    const literal = escapeString(isRegex ? value.replace(REGEX_SPECIAL, '\\$&') : value)
                    return {
                        label: value,
                        insertText: situation.betweenQuotes ? literal : `"${literal}"`,
                        kind: 'value',
                    }
                }),
                incomplete: true,
            }
        }
    }
}
