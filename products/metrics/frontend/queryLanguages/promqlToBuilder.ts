import type { MetricsQueryFilter } from '~/queries/schema/schema-general'

import { COMPARISON_OPS, type PromExpr, PromQLParseError, SET_OPS, parsePromQL, unwrapParens } from './promqlParser'
import { printPromQL } from './promqlPrinter'
import { promRegexToBuilderRegex } from './regex'
import {
    type BuilderClause,
    type BuilderQuery,
    CLAUSE_LABEL,
    type ConversionResult,
    ENGINE_QUANTILE,
    MAX_CONVERTED_CLAUSES,
    clauseAlias,
} from './types'

type ClauseShape = Omit<BuilderClause, 'name'>
type SelectorExpr = Extract<PromExpr, { type: 'selector' }>

const MATCH_OP_TO_FILTER_OP: Record<string, MetricsQueryFilter['op']> = {
    '=': 'eq',
    '!=': 'neq',
    '=~': 'regex',
    '!~': 'not_regex',
}
const SIMPLE_AGGREGATIONS = new Set(['sum', 'avg', 'min', 'max', 'count'])
const COUNTER_FUNCTIONS = new Set(['rate', 'increase', 'irate'])
const FORMULA_OPS = new Set(['+', '-', '*', '/'])
// These keep or drop whole series rather than combine them.
const SELECTION_AGGREGATIONS = new Set(['topk', 'bottomk', 'limitk', 'limit_ratio'])

class ClauseReader {
    constructor(private issues: string[]) {}

    private note(issue: string): void {
        if (!this.issues.includes(issue)) {
            this.issues.push(issue)
        }
    }

    /** Metric name and label filters of a selector. */
    private selectorFields(selector: SelectorExpr): Pick<ClauseShape, 'metricName' | 'filters'> | null {
        let metricName = selector.name
        const filters: MetricsQueryFilter[] = []
        for (const matcher of selector.matchers) {
            if (matcher.label === '__name__') {
                if (matcher.op === '=' && metricName === null) {
                    metricName = matcher.value
                } else {
                    this.note(`The metric name matcher __name__${matcher.op}"${matcher.value}" is not supported.`)
                }
                continue
            }
            const op = MATCH_OP_TO_FILTER_OP[matcher.op]
            filters.push({
                key: matcher.label,
                op,
                value: op === 'regex' || op === 'not_regex' ? promRegexToBuilderRegex(matcher.value) : matcher.value,
            })
        }
        if (!metricName) {
            this.note('A selector without a metric name cannot be converted.')
            return null
        }
        if (selector.offset) {
            this.note(`The offset ${selector.offset} is dropped.`)
        }
        if (selector.at) {
            this.note(`The @ ${selector.at} modifier is dropped.`)
        }
        return { metricName, ...(filters.length ? { filters } : {}) }
    }

    private rangeNote(selector: SelectorExpr): void {
        if (selector.range && !['$__rate_interval', '$__interval'].includes(selector.range)) {
            this.note(`The range [${selector.range}] is replaced by the chart interval.`)
        }
    }

    private groupBy(grouping: { without: boolean; labels: string[] } | undefined): Pick<ClauseShape, 'groupBy'> {
        if (!grouping) {
            return {}
        }
        if (grouping.without) {
            this.note(`"without (${grouping.labels.join(', ')})" is not supported; the series are not grouped.`)
            return {}
        }
        return grouping.labels.length ? { groupBy: grouping.labels.map((key) => ({ key })) } : {}
    }

    /** A counter function over a selector, such as `rate(x[5m])`. */
    private counterCall(expr: PromExpr): { aggregation: 'rate' | 'increase'; selector: SelectorExpr } | null {
        expr = unwrapParens(expr)
        if (expr.type !== 'call' || !COUNTER_FUNCTIONS.has(expr.func) || expr.args.length !== 1) {
            return null
        }
        let arg = unwrapParens(expr.args[0])
        if (arg.type === 'subquery' && unwrapParens(arg.expr).type === 'selector') {
            this.note(`The subquery [${arg.range}:${arg.step ?? ''}] is dropped.`)
            arg = unwrapParens(arg.expr)
        }
        if (arg.type !== 'selector') {
            return null
        }
        if (expr.func === 'irate') {
            this.note('irate() becomes rate() over each chart interval.')
        }
        this.rangeNote(arg)
        return { aggregation: expr.func === 'increase' ? 'increase' : 'rate', selector: arg }
    }

    private numberParam(param: PromExpr | undefined): number | null {
        const value = param ? unwrapParens(param) : undefined
        return value?.type === 'number' && value.value > 0 && value.value < 1 ? value.value : null
    }

    read(expr: PromExpr): ClauseShape | null {
        expr = unwrapParens(expr)
        switch (expr.type) {
            case 'selector': {
                this.rangeNote(expr)
                const fields = this.selectorFields(expr)
                if (!fields) {
                    return null
                }
                this.note(`${fields.metricName} has no aggregation; its series are summed into one line.`)
                return { ...fields, aggregation: 'sum' }
            }
            case 'offset':
                this.note(`The offset ${expr.offset} is dropped.`)
                return this.read(expr.expr)
            case 'subquery':
                this.note(`The subquery [${expr.range}:${expr.step ?? ''}] is dropped.`)
                return this.read(expr.expr)
            case 'aggregate':
                return this.readAggregate(expr)
            case 'call':
                return this.readCall(expr)
            default:
                return null
        }
    }

    private readAggregate(expr: Extract<PromExpr, { type: 'aggregate' }>): ClauseShape | null {
        const inner = unwrapParens(expr.expr)
        const groupBy = this.groupBy(expr.grouping)

        if (SELECTION_AGGREGATIONS.has(expr.op)) {
            this.note(`${expr.op}() is dropped; every series is shown.`)
            return this.read(inner)
        }

        if (expr.op === 'quantile' || expr.op === 'median') {
            const quantile = expr.op === 'median' ? 0.5 : this.numberParam(expr.param)
            if (quantile !== ENGINE_QUANTILE) {
                this.note(`Metrics support only quantile ${ENGINE_QUANTILE}; ${expr.op}() uses it.`)
            }
            if (inner.type !== 'selector') {
                this.note(`Only a plain selector can be inside ${expr.op}(); the inner function is dropped.`)
            }
            const counter = inner.type === 'selector' ? null : this.counterCall(inner)
            const selector = inner.type === 'selector' ? inner : counter?.selector
            if (selector) {
                this.rangeNote(selector)
                const fields = this.selectorFields(selector)
                return fields && { ...fields, aggregation: 'quantile', quantile: ENGINE_QUANTILE, ...groupBy }
            }
            const clause = this.read(inner)
            return clause && { ...clause, aggregation: 'quantile', quantile: ENGINE_QUANTILE, ...groupBy }
        }

        if (!SIMPLE_AGGREGATIONS.has(expr.op)) {
            this.note(`${expr.op}() is not supported; it becomes sum().`)
        }
        const op = SIMPLE_AGGREGATIONS.has(expr.op) ? (expr.op as ClauseShape['aggregation']) : 'sum'

        if (inner.type === 'selector') {
            this.rangeNote(inner)
            const fields = this.selectorFields(inner)
            return fields && { ...fields, aggregation: op, ...groupBy }
        }

        const counter = this.counterCall(inner)
        if (counter) {
            if (op !== 'sum') {
                this.note(
                    `${op}() of ${counter.aggregation}() becomes the sum of the per-series ${counter.aggregation}.`
                )
            }
            const fields = this.selectorFields(counter.selector)
            return fields && { ...fields, aggregation: counter.aggregation, ...groupBy }
        }

        const nested = this.read(inner)
        if (!nested) {
            return null
        }
        this.note(`${expr.op}() over another aggregation is not supported; only the inner aggregation is kept.`)
        const { groupBy: _innerGroupBy, ...rest } = nested
        return { ...rest, ...groupBy }
    }

    private readCall(expr: Extract<PromExpr, { type: 'call' }>): ClauseShape | null {
        if (expr.func === 'histogram_quantile' && expr.args.length === 2) {
            return this.readHistogramQuantile(expr.args[0], expr.args[1])
        }
        const counter = this.counterCall(expr)
        if (counter) {
            const fields = this.selectorFields(counter.selector)
            if (!fields) {
                return null
            }
            this.note(`${expr.func}() without an aggregation is summed over all series of ${fields.metricName}.`)
            return { ...fields, aggregation: counter.aggregation }
        }
        const vectorArg = expr.args.find((arg) => !['number', 'string'].includes(unwrapParens(arg).type))
        this.note(`${expr.func}() is not supported and is dropped.`)
        return vectorArg ? this.read(vectorArg) : null
    }

    private readHistogramQuantile(param: PromExpr, buckets: PromExpr): ClauseShape | null {
        const quantile = this.numberParam(param)
        if (quantile === null) {
            this.note('histogram_quantile() needs a number between 0 and 1; 0.95 is used.')
        }
        buckets = unwrapParens(buckets)
        let groupBy: Pick<ClauseShape, 'groupBy'> = {}
        let counterExpr: PromExpr = buckets
        if (buckets.type === 'aggregate') {
            if (buckets.op !== 'sum') {
                this.note(`histogram_quantile() over ${buckets.op}() is read as over sum().`)
            }
            const labels = buckets.grouping && !buckets.grouping.without ? buckets.grouping.labels : []
            if (!labels.includes('le')) {
                this.note('The buckets are not grouped by "le", so the quantile can differ.')
            }
            groupBy = this.groupBy(
                buckets.grouping && { ...buckets.grouping, labels: labels.filter((label) => label !== 'le') }
            )
            counterExpr = buckets.expr
        } else {
            this.note('histogram_quantile() over buckets that are not summed by "le" adds the buckets of all series.')
        }
        const counter = this.counterCall(counterExpr)
        if (!counter) {
            this.note('histogram_quantile() needs rate() or increase() of a bucket metric.')
            return null
        }
        const fields = this.selectorFields(counter.selector)
        if (!fields) {
            return null
        }
        const metricName = fields.metricName.endsWith('_bucket') ? fields.metricName.slice(0, -7) : fields.metricName
        return { ...fields, metricName, aggregation: 'histogram_quantile', quantile: quantile ?? 0.95, ...groupBy }
    }
}

const clauseKey = (clause: ClauseShape): string => JSON.stringify(clause)

class FormulaBuilder {
    clauses: BuilderClause[] = []
    private aliases = new Map<string, string>()
    private reader: ClauseReader

    constructor(private issues: string[]) {
        this.reader = new ClauseReader(issues)
    }

    private note(issue: string): void {
        if (!this.issues.includes(issue)) {
            this.issues.push(issue)
        }
    }

    addClause(expr: PromExpr, alias?: string): string | null {
        const clause = this.reader.read(expr)
        if (!clause) {
            return null
        }
        const key = clauseKey(clause)
        const existing = this.aliases.get(key)
        if (existing && !alias) {
            return existing
        }
        if (this.clauses.length >= MAX_CONVERTED_CLAUSES) {
            this.note(`A query can have at most ${MAX_CONVERTED_CLAUSES} series; the others are dropped.`)
            return null
        }
        const name = alias ?? clauseAlias(this.clauses.length)
        this.aliases.set(key, name)
        this.clauses.push({ name, ...clause })
        return name
    }

    /** The builder formula for an expression, creating clauses for its vector parts. */
    formula(expr: PromExpr): string | null {
        switch (expr.type) {
            case 'number':
                return Number.isFinite(expr.value) ? String(expr.value) : null
            case 'paren': {
                const inner = this.formula(expr.expr)
                return inner === null ? null : `(${inner})`
            }
            case 'unary': {
                const inner = this.formula(expr.expr)
                return inner === null ? null : expr.op === '-' ? `-${inner}` : inner
            }
            case 'binary':
                return this.binaryFormula(expr)
            case 'aggregate': {
                const inner = unwrapParens(expr.expr)
                if (inner.type === 'binary' && FORMULA_OPS.has(inner.op) && !expr.param) {
                    return this.distributeAggregate(expr, inner)
                }
                return this.addClause(expr)
            }
            default:
                return this.addClause(expr)
        }
    }

    /** `max(a / b)` → `max(a) / max(b)`: the builder aggregates each series before the formula. */
    private distributeAggregate(
        aggregate: Extract<PromExpr, { type: 'aggregate' }>,
        binary: Extract<PromExpr, { type: 'binary' }>
    ): string | null {
        const isNumber = (side: PromExpr): boolean => unwrapParens(side).type === 'number'
        const exact =
            aggregate.op === 'sum' &&
            (['+', '-'].includes(binary.op) ||
                (isNumber(binary.rhs) && ['*', '/'].includes(binary.op)) ||
                (isNumber(binary.lhs) && binary.op === '*'))
        if (!exact) {
            this.note(
                `${aggregate.op}() is applied to each side of "${binary.op}" before the formula, so the result can differ.`
            )
        }
        const wrap = (side: PromExpr): PromExpr => (isNumber(side) ? side : { ...aggregate, expr: side })
        return this.formula({ ...binary, lhs: wrap(binary.lhs), rhs: wrap(binary.rhs) })
    }

    private binaryFormula(expr: Extract<PromExpr, { type: 'binary' }>): string | null {
        if (COMPARISON_OPS.has(expr.op) || SET_OPS.has(expr.op)) {
            this.note(`The "${expr.op} ${printPromQL(expr.rhs)}" part is dropped.`)
            return this.formula(expr.lhs)
        }
        if (!FORMULA_OPS.has(expr.op)) {
            this.note(`The "${expr.op}" operator is not supported; only its left side is kept.`)
            return this.formula(expr.lhs)
        }
        // The builder spreads an ungrouped series over the other side, which is what on() group_x does.
        const broadcast = expr.matching?.on && expr.matching.labels.length === 0 && expr.matching.card !== 'one-to-one'
        if (expr.matching && !broadcast) {
            this.note(
                'Vector matching (on, ignoring, group_left, group_right) is not supported; series match by all labels.'
            )
        }
        if (expr.bool) {
            this.note('The bool modifier is dropped.')
        }
        const lhs = this.formula(expr.lhs)
        const rhs = this.formula(expr.rhs)
        if (lhs === null || rhs === null) {
            return lhs ?? rhs
        }
        // The parse tree keeps explicit parentheses, so operands print in the order PromQL grouped them.
        return `${lhs} ${expr.op} ${rhs}`
    }
}

/** `label_replace(expr, "clause", "a", "", "")`, the form builderToPromql gives each series of a multi-series query. */
const labelledClause = (expr: PromExpr): { alias: string; expr: PromExpr } | null => {
    expr = unwrapParens(expr)
    if (expr.type !== 'call' || expr.func !== 'label_replace' || expr.args.length !== 5) {
        return null
    }
    const [inner, label, value, source, regex] = expr.args.map(unwrapParens)
    const isString = (arg: PromExpr, expected?: string): arg is Extract<PromExpr, { type: 'string' }> =>
        arg.type === 'string' && (expected === undefined || arg.value === expected)
    if (isString(label, CLAUSE_LABEL) && isString(value) && isString(source, '') && isString(regex, '')) {
        return /^[a-z_][a-z0-9_]*$/.test(value.value) ? { alias: value.value, expr: inner } : null
    }
    return null
}

const orOperands = (expr: PromExpr): PromExpr[] => {
    const unwrapped = unwrapParens(expr)
    return unwrapped.type === 'binary' && unwrapped.op === 'or' && !unwrapped.matching
        ? [...orOperands(unwrapped.lhs), ...orOperands(unwrapped.rhs)]
        : [expr]
}

export function promqlToBuilder(text: string): ConversionResult<BuilderQuery> {
    if (!text.trim()) {
        return { value: { clauses: [] }, issues: [] }
    }
    let parsed: PromExpr
    try {
        parsed = parsePromQL(text)
    } catch (error) {
        const message = error instanceof PromQLParseError ? error.message : String(error)
        return { value: null, issues: [`The PromQL cannot be read: ${message}`] }
    }
    const issues: string[] = []
    const builder = new FormulaBuilder(issues)

    const operands = orOperands(parsed)
    if (operands.length > 1) {
        const labelled = operands.map(labelledClause)
        if (labelled.every((operand) => operand !== null)) {
            labelled.forEach((operand) => builder.addClause(operand!.expr, operand!.alias))
        } else {
            issues.push('Each side of "or" becomes its own series; series with the same labels are not merged.')
            operands.forEach((operand) => builder.addClause(operand))
        }
        return builder.clauses.length ? { value: { clauses: builder.clauses }, issues } : { value: null, issues }
    }

    const formula = builder.formula(parsed)
    if (!builder.clauses.length || formula === null) {
        return { value: null, issues: issues.length ? issues : ['The PromQL has no metric to chart.'] }
    }
    const isSingleAlias = builder.clauses.length === 1 && formula === builder.clauses[0].name
    return { value: { clauses: builder.clauses, ...(isSingleAlias ? {} : { formula }) }, issues }
}
