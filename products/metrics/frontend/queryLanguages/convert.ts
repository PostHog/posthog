import type { MetricsQuery, MetricsQueryLanguage } from '~/queries/schema/schema-general'

import { builderToPromql } from './builderToPromql'
import { builderToSql } from './builderToSql'
import { type PromExpr, parsePromQL } from './promqlParser'
import { printPromQL } from './promqlPrinter'
import { promqlToBuilder } from './promqlToBuilder'
import { sqlToBuilder } from './sqlToBuilder'
import { type BuilderQuery, type ConversionResult, clauseAlias, normalizeLabelKey } from './types'

export const METRICS_QUERY_LANGUAGES: MetricsQueryLanguage[] = ['builder', 'promql', 'sql']

export const queryLanguage = (query: Pick<MetricsQuery, 'language'>): MetricsQueryLanguage =>
    query.language ?? 'builder'

/** Shown when a round trip finds a change that no converter reported. */
export const GENERIC_LOSS_ISSUE = 'Some parts of the query cannot be converted exactly and will change.'

/** The builder form of a query in any language. */
export function toBuilderQuery(query: MetricsQuery): ConversionResult<BuilderQuery> {
    switch (queryLanguage(query)) {
        case 'promql':
            return promqlToBuilder(query.promql ?? '')
        case 'sql':
            return sqlToBuilder(query.sql ?? '')
        default:
            return {
                value: { clauses: query.clauses, ...(query.formula ? { formula: query.formula } : {}) },
                issues: [],
            }
    }
}

function fromBuilderQuery(builder: BuilderQuery, to: 'promql' | 'sql'): ConversionResult<string> {
    return to === 'promql' ? builderToPromql(builder) : builderToSql(builder)
}

/**
 * A canonical form of a builder query for comparison: aliases renamed in order, the pinned type
 * dropped (PromQL has no form for it, and the picker sets it again), default scopes and
 * `service.name` normalized, and group-by keys sorted.
 */
export function canonicalBuilder(query: BuilderQuery): string {
    const clauses = query.clauses.filter((clause) => clause.metricName.trim())
    const renames = new Map(clauses.map((clause, index) => [clause.name, clauseAlias(index)]))
    const formula = (query.formula ?? '')
        .replace(/[a-z_][a-z0-9_]*/g, (word) => renames.get(word) ?? word)
        .replace(/\s+/g, '')
    return JSON.stringify({
        clauses: clauses.map((clause) => ({
            metricName: clause.metricName.trim(),
            aggregation: clause.aggregation,
            quantile: ['quantile', 'histogram_quantile'].includes(clause.aggregation)
                ? (clause.quantile ?? 0.95)
                : null,
            filters: (clause.filters ?? []).map((filter) => ({
                key: normalizeLabelKey(filter.key),
                op: filter.op,
                value: filter.value,
                scope: filter.scope === 'auto' ? undefined : filter.scope,
            })),
            groupBy: (clause.groupBy ?? [])
                .map((group) => `${normalizeLabelKey(group.key)}:${group.scope === 'auto' ? '' : (group.scope ?? '')}`)
                .sort(),
        })),
        formula: formula === 'a' && clauses.length === 1 ? '' : formula,
    })
}

const stripParens = (expr: PromExpr): PromExpr => {
    switch (expr.type) {
        case 'paren':
            return stripParens(expr.expr)
        case 'unary':
        case 'offset':
        case 'subquery':
            return { ...expr, expr: stripParens(expr.expr) }
        case 'call':
            return { ...expr, args: expr.args.map(stripParens) }
        case 'aggregate':
            return { ...expr, expr: stripParens(expr.expr), ...(expr.param ? { param: stripParens(expr.param) } : {}) }
        case 'binary':
            return { ...expr, lhs: stripParens(expr.lhs), rhs: stripParens(expr.rhs) }
        case 'selector': {
            // A Grafana step variable means the same as an omitted range.
            const { range, ...rest } = expr
            return range?.startsWith('$__') && range !== '$__range' ? rest : expr
        }
        default:
            return expr
    }
}

/** PromQL in canonical form: one spelling of each construct, and only the parentheses it needs. */
export function canonicalPromQL(text: string): string | null {
    try {
        return printPromQL(stripParens(parsePromQL(text)))
    } catch {
        return null
    }
}

/** SQL without formatting differences: comments, spacing and keyword case. */
export function canonicalSql(text: string): string {
    return text
        .replace(/--[^\n]*/g, '')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\s+/g, ' ')
        .replace(/\s*([(),=<>+\-*/])\s*/g, '$1')
        .replace(/;$/, '')
        .trim()
        .toLowerCase()
}

const sourceText = (query: MetricsQuery, language: MetricsQueryLanguage): string =>
    language === 'promql' ? (query.promql ?? '') : language === 'sql' ? (query.sql ?? '') : ''

/** Whether the text in `language` comes back unchanged from the builder form. */
function textSurvives(text: string, builder: BuilderQuery, language: 'promql' | 'sql'): boolean {
    const again = fromBuilderQuery(builder, language).value
    if (again === null) {
        return false
    }
    if (language === 'promql') {
        return canonicalPromQL(again) === canonicalPromQL(text)
    }
    return canonicalSql(again) === canonicalSql(text)
}

function builderSurvives(builder: BuilderQuery, text: string, language: 'promql' | 'sql'): boolean {
    const back = (language === 'promql' ? promqlToBuilder(text) : sqlToBuilder(text)).value
    return back !== null && canonicalBuilder(back) === canonicalBuilder(builder)
}

export interface MetricsQueryConversion {
    query: MetricsQuery
    /** What the switch loses or changes. Empty when the switch is lossless. */
    issues: string[]
}

/** Converts a metrics query to another language, best effort. Shared fields (date range, interval, display) are kept. */
export function convertMetricsQuery(query: MetricsQuery, to: MetricsQueryLanguage): MetricsQueryConversion {
    const from = queryLanguage(query)
    if (from === to) {
        return { query, issues: [] }
    }
    const { promql: _promql, sql: _sql, language: _language, formula: _formula, ...shared } = query
    const issues: string[] = []
    const source = toBuilderQuery(query)
    issues.push(...source.issues)
    const builder = source.value

    if (to === 'builder') {
        const clauses = builder?.clauses ?? []
        if (from !== 'builder' && builder && !issues.length && !textSurvives(sourceText(query, from), builder, from)) {
            issues.push(GENERIC_LOSS_ISSUE)
        }
        return {
            query: { ...shared, clauses, ...(builder?.formula ? { formula: builder.formula } : {}) },
            issues: dedupe(issues),
        }
    }

    const target = builder ? fromBuilderQuery(builder, to) : { value: null, issues: [] }
    issues.push(...target.issues)
    const text = target.value ?? ''
    if (builder && target.value !== null && !issues.length) {
        const survives =
            from === 'builder'
                ? builderSurvives(builder, text, to)
                : textSurvives(sourceText(query, from), builder, from) && builderSurvives(builder, text, to)
        if (!survives) {
            issues.push(GENERIC_LOSS_ISSUE)
        }
    }
    return {
        query: { ...shared, clauses: [], language: to, ...(to === 'promql' ? { promql: text } : { sql: text }) },
        issues: dedupe(issues),
    }
}

const dedupe = (issues: string[]): string[] => [...new Set(issues)]
