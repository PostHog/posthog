import { type Matcher, type PromExpr, PromQLParseError, parsePromQL, unwrapParens } from './promqlParser'
import { printPromQL } from './promqlPrinter'
import { builderRegexToPromRegex } from './regex'
import { type BuilderClause, type BuilderQuery, CLAUSE_LABEL, type ConversionResult, normalizeLabelKey } from './types'

const FILTER_OP_TO_MATCH_OP: Record<string, Matcher['op']> = {
    eq: '=',
    neq: '!=',
    regex: '=~',
    not_regex: '!~',
}

const SIMPLE_AGGREGATIONS = new Set(['sum', 'avg', 'min', 'max', 'count'])

interface ClauseExpr {
    expr: PromExpr
    /** Labels the clause groups by, sorted; used to pick vector matching in a formula. */
    labels: string[]
}

function clauseToPromExpr(clause: BuilderClause, issues: string[]): ClauseExpr {
    const matchers: Matcher[] = []
    for (const filter of clause.filters ?? []) {
        if (filter.scope && filter.scope !== 'auto') {
            issues.push(
                `PromQL cannot limit "${filter.key}" to ${filter.scope} attributes in series ${clause.name}; the filter matches both.`
            )
        }
        const op = FILTER_OP_TO_MATCH_OP[filter.op]
        matchers.push({
            label: normalizeLabelKey(filter.key),
            op,
            value: op === '=~' || op === '!~' ? builderRegexToPromRegex(filter.value) : filter.value,
        })
    }
    for (const groupBy of clause.groupBy ?? []) {
        if (groupBy.scope && groupBy.scope !== 'auto') {
            issues.push(
                `PromQL cannot limit the "${groupBy.key}" group-by to ${groupBy.scope} attributes in series ${clause.name}.`
            )
        }
    }
    // The pinned OTel type has no PromQL form. It is not reported: the picker sets it on every
    // clause, and it only matters for the rare name that exists as more than one type.
    const labels = [...new Set((clause.groupBy ?? []).map((groupBy) => normalizeLabelKey(groupBy.key)))]
    const grouping = labels.length ? { without: false, labels } : undefined
    const selector: PromExpr = { type: 'selector', name: clause.metricName, matchers }

    let expr: PromExpr
    switch (clause.aggregation) {
        case 'rate':
        case 'increase':
            // An omitted range uses the query step, which is how the builder computes per-bucket rates.
            expr = {
                type: 'aggregate',
                op: 'sum',
                expr: { type: 'call', func: clause.aggregation, args: [selector] },
                ...(grouping ? { grouping } : {}),
            }
            break
        case 'quantile':
            expr = {
                type: 'aggregate',
                op: 'quantile',
                param: { type: 'number', value: clause.quantile ?? 0.95 },
                expr: selector,
                ...(grouping ? { grouping } : {}),
            }
            break
        case 'histogram_quantile':
            expr = {
                type: 'call',
                func: 'histogram_quantile',
                args: [
                    { type: 'number', value: clause.quantile ?? 0.95 },
                    {
                        type: 'aggregate',
                        op: 'sum',
                        grouping: { without: false, labels: ['le', ...labels.filter((label) => label !== 'le')] },
                        expr: {
                            type: 'call',
                            func: 'rate',
                            args: [{ ...selector, name: `${clause.metricName}_bucket` }],
                        },
                    },
                ],
            }
            break
        default:
            if (!SIMPLE_AGGREGATIONS.has(clause.aggregation)) {
                issues.push(`PromQL has no "${clause.aggregation}" aggregation; series ${clause.name} uses sum.`)
            }
            expr = {
                type: 'aggregate',
                op: SIMPLE_AGGREGATIONS.has(clause.aggregation) ? clause.aggregation : 'sum',
                expr: selector,
                ...(grouping ? { grouping } : {}),
            }
    }
    return { expr, labels: [...labels].sort() }
}

const sameLabels = (a: string[], b: string[]): boolean => a.length === b.length && a.every((label, i) => label === b[i])

/** Replaces the aliases in a parsed builder formula with clause expressions, adding vector matching. */
function substituteFormula(
    node: PromExpr,
    clauses: Map<string, ClauseExpr>,
    used: Set<string>,
    issues: string[]
): { expr: PromExpr; labels: string[] | null } {
    switch (node.type) {
        case 'number':
            return { expr: node, labels: null }
        case 'paren': {
            const inner = substituteFormula(node.expr, clauses, used, issues)
            return { expr: { type: 'paren', expr: inner.expr }, labels: inner.labels }
        }
        case 'unary': {
            const inner = substituteFormula(node.expr, clauses, used, issues)
            return { expr: { ...node, expr: inner.expr }, labels: inner.labels }
        }
        case 'selector': {
            const clause = node.name !== null ? clauses.get(node.name) : undefined
            if (!clause || node.matchers.length) {
                throw new Error(`The formula refers to an unknown series "${node.name ?? ''}"`)
            }
            used.add(node.name as string)
            return clause
        }
        case 'binary': {
            const lhs = substituteFormula(node.lhs, clauses, used, issues)
            const rhs = substituteFormula(node.rhs, clauses, used, issues)
            const binary: PromExpr = { type: 'binary', op: node.op, lhs: lhs.expr, rhs: rhs.expr }
            if (lhs.labels === null || rhs.labels === null) {
                return { expr: binary, labels: lhs.labels ?? rhs.labels }
            }
            if (sameLabels(lhs.labels, rhs.labels)) {
                return { expr: binary, labels: lhs.labels }
            }
            // The builder spreads an ungrouped series over every label set of the other side.
            if (rhs.labels.length === 0) {
                return {
                    expr: { ...binary, matching: { card: 'many-to-one', on: true, labels: [], include: [] } },
                    labels: lhs.labels,
                }
            }
            if (lhs.labels.length === 0) {
                return {
                    expr: { ...binary, matching: { card: 'one-to-many', on: true, labels: [], include: [] } },
                    labels: rhs.labels,
                }
            }
            issues.push(
                'The formula combines series grouped by different labels. PromQL only matches series with the same labels.'
            )
            return { expr: binary, labels: lhs.labels }
        }
        default:
            throw new Error('The formula has an unsupported term')
    }
}

export function builderToPromql(query: BuilderQuery): ConversionResult<string> {
    const issues: string[] = []
    const clauses = query.clauses.filter((clause) => clause.metricName.trim())
    if (clauses.length === 0) {
        return { value: '', issues }
    }
    const exprs = new Map(clauses.map((clause) => [clause.name, clauseToPromExpr(clause, issues)]))

    const formula = query.formula?.trim()
    if (formula) {
        let parsed: PromExpr
        try {
            parsed = parsePromQL(formula)
        } catch (error) {
            const message = error instanceof PromQLParseError ? error.message : String(error)
            return { value: null, issues: [`The formula "${formula}" cannot be read: ${message}`] }
        }
        const used = new Set<string>()
        try {
            const result = substituteFormula(parsed, exprs, used, issues)
            const unused = clauses.filter((clause) => !used.has(clause.name)).map((clause) => clause.name)
            if (unused.length) {
                issues.push(
                    `Series ${unused.join(', ')} ${unused.length > 1 ? 'are' : 'is'} not in the formula and will be removed.`
                )
            }
            return { value: printPromQL(unwrapParens(result.expr)), issues }
        } catch (error) {
            return { value: null, issues: [error instanceof Error ? error.message : String(error)] }
        }
    }

    if (clauses.length === 1) {
        return { value: printPromQL(exprs.get(clauses[0].name)!.expr), issues }
    }

    // Several series without a formula: label each one with its alias, so the union keeps them apart.
    const labelled: PromExpr[] = clauses.map((clause) => ({
        type: 'call',
        func: 'label_replace',
        args: [
            exprs.get(clause.name)!.expr,
            { type: 'string', value: CLAUSE_LABEL },
            { type: 'string', value: clause.name },
            { type: 'string', value: '' },
            { type: 'string', value: '' },
        ],
    }))
    const union = labelled.reduce((lhs, rhs) => ({ type: 'binary', op: 'or', lhs, rhs }))
    return { value: printPromQL(union), issues }
}
