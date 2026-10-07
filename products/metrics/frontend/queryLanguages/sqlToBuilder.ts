import type { MetricsAttributeScope, MetricsQueryFilter, MetricsQueryGroupBy } from '~/queries/schema/schema-general'

import {
    type BuilderClause,
    type BuilderQuery,
    type ConversionResult,
    ENGINE_QUANTILE,
    MAX_CONVERTED_CLAUSES,
    clauseAlias,
} from './types'

/**
 * SQL → builder, best effort.
 *
 * This is not a SQL parser. It splits the statement into its SELECT parts and recognizes the
 * shapes builderToSql writes, plus the simple queries people write by hand
 * (`SELECT toStartOfInterval(timestamp, {interval}) AS time, avg(value) AS value FROM posthog.metrics …`).
 * Every part it does not recognize becomes an issue, so the caller can warn before it drops it.
 */

type TokenType = 'word' | 'quoted' | 'string' | 'number' | 'placeholder' | 'punct'

interface Token {
    type: TokenType
    value: string
}

export class SqlReadError extends Error {}

const PUNCTUATION = [
    '!=',
    '>=',
    '<=',
    '<>',
    '==',
    '->',
    '(',
    ')',
    ',',
    '.',
    '=',
    '<',
    '>',
    '+',
    '-',
    '*',
    '/',
    '[',
    ']',
    '%',
]

function tokenize(sql: string): Token[] {
    const tokens: Token[] = []
    let i = 0
    while (i < sql.length) {
        const ch = sql[i]
        const rest = sql.slice(i)
        if (/\s/.test(ch)) {
            i++
        } else if (rest.startsWith('--')) {
            const end = sql.indexOf('\n', i)
            i = end === -1 ? sql.length : end
        } else if (rest.startsWith('/*')) {
            const end = sql.indexOf('*/', i + 2)
            i = end === -1 ? sql.length : end + 2
        } else if (ch === "'" || ch === '`' || ch === '"') {
            let value = ''
            let j = i + 1
            while (j < sql.length && sql[j] !== ch) {
                if (sql[j] === '\\' && j + 1 < sql.length) {
                    value += sql[j + 1]
                    j += 2
                    continue
                }
                value += sql[j]
                j++
            }
            if (j >= sql.length) {
                throw new SqlReadError('The SQL has a quote that is not closed.')
            }
            tokens.push({ type: ch === "'" ? 'string' : 'quoted', value })
            i = j + 1
        } else if (ch === '{') {
            const end = sql.indexOf('}', i)
            if (end === -1) {
                throw new SqlReadError('The SQL has a placeholder that is not closed.')
            }
            tokens.push({ type: 'placeholder', value: sql.slice(i + 1, end).trim() })
            i = end + 1
        } else if (/[0-9]/.test(ch) || (ch === '.' && /[0-9]/.test(sql[i + 1] ?? ''))) {
            const match = /^(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?/.exec(rest)!
            tokens.push({ type: 'number', value: match[0] })
            i += match[0].length
        } else if (/[a-zA-Z_]/.test(ch)) {
            const match = /^[a-zA-Z_][a-zA-Z0-9_$]*/.exec(rest)!
            tokens.push({ type: 'word', value: match[0] })
            i += match[0].length
        } else {
            const op = PUNCTUATION.find((candidate) => rest.startsWith(candidate))
            if (!op) {
                throw new SqlReadError(`The SQL has a character that cannot be read: "${ch}".`)
            }
            tokens.push({ type: 'punct', value: op })
            i += op.length
        }
    }
    return tokens
}

const isWord = (token: Token | undefined, ...words: string[]): boolean =>
    token?.type === 'word' && words.includes(token.value.toUpperCase())
const isPunct = (token: Token | undefined, value: string): boolean => token?.type === 'punct' && token.value === value

/** Canonical text of a token run, for comparing expressions without caring about spacing or quoting style. */
function canon(tokens: Token[]): string {
    return tokens
        .map((token, i) => {
            const text =
                token.type === 'string'
                    ? JSON.stringify(token.value)
                    : token.type === 'quoted'
                      ? `\`${token.value}\``
                      : token.type === 'placeholder'
                        ? `{${token.value}}`
                        : token.value
            const previous = tokens[i - 1]
            const needsSpace =
                previous && /^[a-zA-Z0-9_]/.test(text) && previous.type !== 'punct' && previous.type !== 'placeholder'
            return needsSpace ? ` ${text}` : text
        })
        .join('')
}

/** Splits a token run at depth-0 tokens that `isSeparator` accepts, dropping the separators. */
function splitTopLevel(tokens: Token[], isSeparator: (tokens: Token[], index: number) => number): Token[][] {
    const parts: Token[][] = []
    let current: Token[] = []
    let depth = 0
    for (let i = 0; i < tokens.length; i++) {
        const token = tokens[i]
        if (isPunct(token, '(') || isPunct(token, '[')) {
            depth++
        } else if (isPunct(token, ')') || isPunct(token, ']')) {
            depth--
        }
        const width = depth === 0 ? isSeparator(tokens, i) : 0
        if (width > 0) {
            parts.push(current)
            current = []
            i += width - 1
            continue
        }
        current.push(token)
    }
    parts.push(current)
    return parts
}

const commaSeparator = (tokens: Token[], i: number): number => (isPunct(tokens[i], ',') ? 1 : 0)
const andSeparator = (tokens: Token[], i: number): number => (isWord(tokens[i], 'AND') ? 1 : 0)
const unionSeparator = (tokens: Token[], i: number): number =>
    isWord(tokens[i], 'UNION') && isWord(tokens[i + 1], 'ALL') ? 2 : 0

/** Removes parentheses that wrap the whole run. */
function unwrap(tokens: Token[]): Token[] {
    while (tokens.length >= 2 && isPunct(tokens[0], '(') && isPunct(tokens[tokens.length - 1], ')')) {
        let depth = 0
        let closesAtEnd = true
        for (let i = 0; i < tokens.length; i++) {
            if (isPunct(tokens[i], '(')) {
                depth++
            } else if (isPunct(tokens[i], ')')) {
                depth--
                if (depth === 0 && i !== tokens.length - 1) {
                    closesAtEnd = false
                    break
                }
            }
        }
        if (!closesAtEnd) {
            break
        }
        tokens = tokens.slice(1, -1)
    }
    return tokens
}

interface Column {
    expr: Token[]
    alias: string | null
}

interface Join {
    source: Source
    alias: string | null
}

type Source = { kind: 'table'; name: string } | { kind: 'subquery'; tokens: Token[] }

interface SelectParts {
    columns: Column[]
    source: Source | null
    sourceAlias: string | null
    joins: Join[]
    where: Token[][]
    groupBy: Token[][]
    having: Token[]
    limit: Token[]
}

const CLAUSE_KEYWORDS = ['FROM', 'WHERE', 'GROUP', 'HAVING', 'ORDER', 'LIMIT', 'SETTINGS']
const JOIN_WORDS = ['LEFT', 'RIGHT', 'INNER', 'FULL', 'CROSS', 'JOIN', 'OUTER', 'ANY', 'ALL', 'ASOF', 'SEMI', 'ANTI']

function parseColumn(tokens: Token[]): Column {
    const last = tokens[tokens.length - 1]
    if (
        tokens.length >= 3 &&
        isWord(tokens[tokens.length - 2], 'AS') &&
        (last.type === 'word' || last.type === 'quoted')
    ) {
        return { expr: tokens.slice(0, -2), alias: last.value }
    }
    if (tokens.length === 1 && tokens[0].type === 'word') {
        return { expr: tokens, alias: tokens[0].value }
    }
    if (tokens.length === 3 && isPunct(tokens[1], '.') && (tokens[2].type === 'word' || tokens[2].type === 'quoted')) {
        return { expr: tokens, alias: tokens[2].value }
    }
    return { expr: tokens, alias: null }
}

/** Reads `<table or (subquery)> [AS] alias`, returning the source and the tokens after it. */
function parseSource(tokens: Token[]): { source: Source; alias: string | null; rest: Token[] } {
    let index = 0
    let source: Source
    if (isPunct(tokens[0], '(')) {
        let depth = 0
        for (; index < tokens.length; index++) {
            if (isPunct(tokens[index], '(')) {
                depth++
            } else if (isPunct(tokens[index], ')') && --depth === 0) {
                break
            }
        }
        source = { kind: 'subquery', tokens: tokens.slice(1, index) }
        index++
    } else {
        const name: string[] = []
        while (index < tokens.length && (tokens[index].type === 'word' || tokens[index].type === 'quoted')) {
            if (isWord(tokens[index], ...JOIN_WORDS, 'AS', 'ON') && name.length) {
                break
            }
            name.push(tokens[index].value)
            index++
            if (!isPunct(tokens[index], '.')) {
                break
            }
            index++
        }
        source = { kind: 'table', name: name.join('.') }
    }
    let alias: string | null = null
    if (isWord(tokens[index], 'AS')) {
        index++
    }
    if (
        tokens[index] &&
        (tokens[index].type === 'word' || tokens[index].type === 'quoted') &&
        !isWord(tokens[index], ...JOIN_WORDS, 'ON')
    ) {
        alias = tokens[index].value
        index++
    }
    return { source, alias, rest: tokens.slice(index) }
}

function parseSelect(tokens: Token[]): SelectParts {
    tokens = unwrap(tokens)
    if (isWord(tokens[0], 'WITH')) {
        throw new SqlReadError('Common table expressions (WITH) are not supported.')
    }
    if (!isWord(tokens[0], 'SELECT')) {
        throw new SqlReadError('The SQL must start with SELECT.')
    }
    const sections: Record<string, Token[]> = {}
    let current = 'SELECT'
    let depth = 0
    sections[current] = []
    for (let i = 1; i < tokens.length; i++) {
        const token = tokens[i]
        if (isPunct(token, '(')) {
            depth++
        } else if (isPunct(token, ')')) {
            depth--
        }
        if (depth === 0 && isWord(token, ...CLAUSE_KEYWORDS)) {
            current = token.value.toUpperCase()
            if ((current === 'GROUP' || current === 'ORDER') && isWord(tokens[i + 1], 'BY')) {
                i++
            }
            sections[current] = []
            continue
        }
        sections[current].push(token)
    }
    if (isWord(sections.SELECT[0], 'DISTINCT')) {
        throw new SqlReadError('SELECT DISTINCT is not supported.')
    }

    let source: Source | null = null
    let sourceAlias: string | null = null
    const joins: Join[] = []
    if (sections.FROM?.length) {
        const parsed = parseSource(sections.FROM)
        source = parsed.source
        sourceAlias = parsed.alias
        let rest = parsed.rest
        while (rest.length) {
            while (rest.length && isWord(rest[0], ...JOIN_WORDS)) {
                rest = rest.slice(1)
            }
            const join = parseSource(rest)
            joins.push({ source: join.source, alias: join.alias })
            rest = join.rest
            if (isWord(rest[0], 'ON', 'USING')) {
                const next = rest.findIndex(
                    (token, i) => i > 0 && isWord(token, 'LEFT', 'RIGHT', 'INNER', 'FULL', 'CROSS', 'JOIN')
                )
                rest = next === -1 ? [] : rest.slice(next)
            }
        }
    }
    return {
        columns: splitTopLevel(sections.SELECT, commaSeparator).map(parseColumn),
        source,
        sourceAlias,
        joins,
        where: sections.WHERE ? splitTopLevel(sections.WHERE, andSeparator) : [],
        groupBy: sections.GROUP ? splitTopLevel(sections.GROUP, commaSeparator) : [],
        having: sections.HAVING ?? [],
        limit: sections.LIMIT ?? [],
    }
}

const STRING = `"(?:[^"\\\\]|\\\\.)*"`
const FIELD_PATTERNS: [RegExp, (match: RegExpExecArray) => { key: string; scope?: MetricsAttributeScope }][] = [
    [/^(?:\w+\.)?service_name$/i, () => ({ key: 'service_name' })],
    [
        new RegExp(`^arrayElement\\((resource_attributes|attributes),(${STRING})\\)$`, 'i'),
        (m) => ({ key: JSON.parse(m[2]), scope: m[1].toLowerCase() === 'attributes' ? 'attribute' : 'resource' }),
    ],
    [
        new RegExp(`^(resource_attributes|attributes)\\[(${STRING})\\]$`, 'i'),
        (m) => ({ key: JSON.parse(m[2]), scope: m[1].toLowerCase() === 'attributes' ? 'attribute' : 'resource' }),
    ],
    [
        new RegExp(
            `^if\\(arrayElement\\(resource_attributes,(${STRING})\\)!="",arrayElement\\(resource_attributes,\\1\\),arrayElement\\(attributes,\\1\\)\\)$`,
            'i'
        ),
        (m) => ({ key: JSON.parse(m[1]) }),
    ],
    [/^toString\((.*)\)$/i, (m) => readField(m[1]) ?? { key: '' }],
]

function readField(text: string): { key: string; scope?: MetricsAttributeScope } | null {
    for (const [pattern, read] of FIELD_PATTERNS) {
        const match = pattern.exec(text)
        if (match) {
            const field = read(match)
            return field.key ? field : null
        }
    }
    return null
}

const withScope = <T extends { key: string }>(item: T, scope: MetricsAttributeScope | undefined): T =>
    scope && scope !== 'auto' ? { ...item, scope } : item

const toBuilderRegex = (values: string[]): string =>
    `^(?:${values.map((value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})$`

class ClauseSqlReader {
    clause: Partial<BuilderClause> & { filters: MetricsQueryFilter[] } = { filters: [] }

    constructor(private issues: string[]) {}

    private note(issue: string): void {
        if (!this.issues.includes(issue)) {
            this.issues.push(issue)
        }
    }

    /** One WHERE condition of the points query or the series subquery. */
    private readCondition(tokens: Token[]): void {
        const text = canon(unwrap(tokens))
        const nameMatch = new RegExp(`^metric_name=(${STRING})$`, 'i').exec(text)
        if (nameMatch) {
            const name = JSON.parse(nameMatch[1])
            if (this.clause.metricName && this.clause.metricName !== name) {
                this.note(
                    `The SQL reads more than one metric (${this.clause.metricName}, ${name}); only the first is kept.`
                )
            } else {
                this.clause.metricName = name
            }
            return
        }
        const typeMatch = new RegExp(`^metric_type=(${STRING})$`, 'i').exec(text)
        if (typeMatch) {
            this.clause.metricType = JSON.parse(typeMatch[1])
            return
        }
        // Time bounds come from the chart's date range and interval.
        if (
            /^(timestamp|last_seen|time_bucket)(>=|<|<=|>)/i.test(text) ||
            /^notEmpty\(histogram_counts\)$/i.test(text)
        ) {
            if (!/\{(date_from|date_to)\}/.test(text) && !/histogram_counts/.test(text)) {
                this.note(`The fixed time bound "${text}" is replaced by the chart date range.`)
            }
            return
        }
        const scoped = /^series_fingerprint IN\((.*)\)$/i.exec(text)
        if (scoped) {
            this.readSeriesSubquery(unwrap(tokens).slice(2))
            return
        }
        if (this.readFilter(text)) {
            return
        }
        this.note(`The condition "${text}" is not supported and is dropped.`)
    }

    private readFilter(text: string): boolean {
        const negated = /^NOT\s*/i.exec(text)
        const body = negated ? text.slice(negated[0].length) : text
        const match = new RegExp(`^match\\((.*),(${STRING})\\)$`, 'i').exec(body)
        if (match) {
            const field = readField(match[1].trim())
            if (field) {
                this.clause.filters.push(
                    withScope(
                        { key: field.key, op: negated ? 'not_regex' : 'regex', value: JSON.parse(match[2]) },
                        field.scope
                    )
                )
                return true
            }
        }
        if (negated) {
            return false
        }
        const comparison = new RegExp(`^(.*?)(!=|<>|==|=)(${STRING})$`).exec(text)
        if (comparison) {
            const field = readField(comparison[1].trim())
            if (field) {
                this.clause.filters.push(
                    withScope(
                        {
                            key: field.key,
                            op: comparison[2] === '=' || comparison[2] === '==' ? 'eq' : 'neq',
                            value: JSON.parse(comparison[3]),
                        },
                        field.scope
                    )
                )
                return true
            }
        }
        const inList = new RegExp(`^(.*?)(NOT IN|IN)\\(((?:${STRING},?)+)\\)$`, 'i').exec(text)
        if (inList) {
            const field = readField(inList[1].trim())
            const values = [...inList[3].matchAll(new RegExp(STRING, 'g'))].map((m) => JSON.parse(m[0]) as string)
            if (field && values.length) {
                const op = inList[2].toUpperCase() === 'IN' ? 'regex' : 'not_regex'
                this.clause.filters.push(withScope({ key: field.key, op, value: toBuilderRegex(values) }, field.scope))
                return true
            }
        }
        return false
    }

    private readSeriesSubquery(tokens: Token[]): void {
        const select = parseSelect(unwrap(tokens))
        if (select.source?.kind !== 'table' || !/(^|\.)metric_series$/i.test(select.source.name)) {
            this.note('A series filter that does not read posthog.metric_series is dropped.')
            return
        }
        select.where.forEach((condition) => this.readCondition(condition))
    }

    readPoints(select: SelectParts): void {
        select.where.forEach((condition) => this.readCondition(condition))
    }
}

const isMetricsTable = (source: Source | null): boolean =>
    source?.kind === 'table' && /(^|\.)(metrics|metric_samples)$/i.test(source.name)

const SIMPLE_AGGREGATIONS: Record<string, BuilderClause['aggregation']> = {
    sum: 'sum',
    avg: 'avg',
    min: 'min',
    max: 'max',
    count: 'count',
}

// Result columns, and the histogram columns builderToSql passes between its selects.
const NON_LABEL_COLUMNS = new Set(['time', 'value', 'clause', 'bounds', 'counts', 'series_fingerprints'])

interface ReadClause {
    clause: BuilderClause
    /** Alias from a `'a' AS clause` column. */
    label: string | null
}

/** Reads one clause from a single SELECT and the subqueries in its FROM. */
function readClauseSelect(tokens: Token[], issues: string[]): ReadClause | null {
    const note = (issue: string): void => {
        if (!issues.includes(issue)) {
            issues.push(issue)
        }
    }
    const chain: SelectParts[] = [parseSelect(tokens)]
    while (chain[chain.length - 1].source?.kind === 'subquery') {
        const source = chain[chain.length - 1].source as Extract<Source, { kind: 'subquery' }>
        if (splitTopLevel(source.tokens, unionSeparator).length > 1) {
            note('A UNION inside a series is not supported.')
            return null
        }
        chain.push(parseSelect(source.tokens))
    }
    const points = chain[chain.length - 1]
    if (!isMetricsTable(points.source)) {
        note('The SQL does not read posthog.metrics.')
        return null
    }
    const reader = new ClauseSqlReader(issues)
    reader.readPoints(points)
    if (!reader.clause.metricName) {
        note('The SQL has no metric_name condition, so there is no metric to chart.')
        return null
    }

    const allText = chain.flatMap((select) => select.columns.map((column) => canon(column.expr))).join(' ')
    const outer = chain[0]
    const valueColumn = outer.columns.find((column) => column.alias?.toLowerCase() === 'value')
    if (!valueColumn) {
        note('The SQL has no "value" column.')
        return null
    }
    const valueText = canon(valueColumn.expr).replace(/^toFloat(?:64)?\((.*)\)$/i, '$1')
    const timeColumn = outer.columns.find((column) => column.alias?.toLowerCase() === 'time')
    if (
        !timeColumn ||
        (!/\{interval\}/.test(canon(timeColumn.expr)) && !/^(\w+\.)?time$/i.test(canon(timeColumn.expr)))
    ) {
        note('The time buckets are replaced by the chart interval.')
    }
    if (chain.some((select) => select.limit.length)) {
        note('LIMIT is dropped.')
    }

    let aggregation: BuilderClause['aggregation']
    let quantile: number | undefined
    if (/histogram_counts|sumForEach/i.test(allText)) {
        aggregation = 'histogram_quantile'
        const rank = /(\d*\.?\d+)\*arraySum\(counts\)/i.exec(allText)
        quantile = rank ? Number(rank[1]) : 0.95
        if (!rank) {
            note('The histogram quantile cannot be found; 0.95 is used.')
        }
    } else if (/lagInFrame/i.test(allText)) {
        aggregation = /\/\{interval_seconds\}$/.test(valueText) ? 'rate' : 'increase'
    } else {
        const quantileMatch = /^quantile\((\d*\.?\d+)\)\((.*)\)$/i.exec(valueText)
        const simpleMatch = /^(\w+)\((.*)\)$/.exec(valueText)
        if (quantileMatch) {
            aggregation = 'quantile'
            quantile = ENGINE_QUANTILE
            if (Number(quantileMatch[1]) !== ENGINE_QUANTILE) {
                note(`Metrics support only quantile ${ENGINE_QUANTILE}; quantile(${quantileMatch[1]}) uses it.`)
            }
        } else if (simpleMatch && SIMPLE_AGGREGATIONS[simpleMatch[1].toLowerCase()]) {
            aggregation = SIMPLE_AGGREGATIONS[simpleMatch[1].toLowerCase()]
        } else {
            note(`The value "${valueText}" is not a supported aggregation; sum is used.`)
            aggregation = 'sum'
        }
        // The builder reduces each series to its last value per bucket before it aggregates.
        if (chain.length === 1) {
            note(
                aggregation === 'count'
                    ? 'The SQL counts samples; the builder counts series.'
                    : 'The SQL aggregates every sample; the builder aggregates the last value of each series in each interval.'
            )
        }
    }

    // Group-by labels: the select that joins posthog.metric_series names them group_0, group_1, …
    // Without a join, the outer select reads label columns directly.
    const groupBy: MetricsQueryGroupBy[] = []
    let label: string | null = null
    const labelSelect = chain.find((select) => select.joins.some((join) => join.source.kind === 'subquery')) ?? outer
    const groupFields = new Map<string, { key: string; scope?: MetricsAttributeScope }>()
    for (const join of labelSelect.joins) {
        if (join.source.kind !== 'subquery') {
            continue
        }
        for (const column of parseSelect(join.source.tokens).columns) {
            const field = /^any\((.*)\)$/i.exec(canon(column.expr))
            const read = field ? readField(field[1]) : null
            if (column.alias && read) {
                groupFields.set(column.alias, read)
            }
        }
    }
    for (const column of labelSelect.columns) {
        const alias = column.alias?.toLowerCase()
        if (alias === 'clause' && column.expr.length === 1 && column.expr[0].type === 'string') {
            label = column.expr[0].value
            continue
        }
        if (!alias || NON_LABEL_COLUMNS.has(alias)) {
            continue
        }
        const text = canon(column.expr)
        const groupMatch = /^(?:\w+\.)?(group_\d+)$/.exec(text)
        const field = groupMatch ? groupFields.get(groupMatch[1]) : readField(text)
        if (field) {
            groupBy.push(withScope({ key: field.key }, field.scope))
        } else if (text !== '""') {
            note(`The column "${column.alias}" is not a label the builder can group by and is dropped.`)
        }
    }

    const { metricName, metricType, filters } = reader.clause
    return {
        clause: {
            name: '',
            metricName: metricName!,
            aggregation,
            ...(metricType ? { metricType } : {}),
            ...(filters.length ? { filters } : {}),
            ...(groupBy.length ? { groupBy } : {}),
            ...(quantile !== undefined ? { quantile } : {}),
        } as BuilderClause,
        label,
    }
}

const FORMULA_TOKEN = /^[a-z_][a-z0-9_]*$|^\d*\.?\d+$|^[-+*/()]$/

export function sqlToBuilder(sql: string): ConversionResult<BuilderQuery> {
    if (!sql.trim()) {
        return { value: { clauses: [] }, issues: [] }
    }
    const issues: string[] = []
    const tooCustom = (): ConversionResult<BuilderQuery> => ({
        value: null,
        issues: [...issues, 'This SQL cannot be converted.'],
    })
    try {
        const tokens = tokenize(sql.trim().replace(/;\s*$/, ''))
        const branches = splitTopLevel(tokens, unionSeparator)

        if (branches.length > 1) {
            const clauses: BuilderClause[] = []
            for (const branch of branches.slice(0, MAX_CONVERTED_CLAUSES)) {
                const read = readClauseSelect(branch, issues)
                if (!read) {
                    return tooCustom()
                }
                clauses.push({ ...read.clause, name: read.label ?? clauseAlias(clauses.length) })
            }
            if (branches.length > MAX_CONVERTED_CLAUSES) {
                issues.push(`A query can have at most ${MAX_CONVERTED_CLAUSES} series; the others are dropped.`)
            }
            return { value: { clauses: dedupeNames(clauses) }, issues }
        }

        const formula = readFormula(tokens, issues)
        if (formula) {
            return formula.value ? formula : tooCustom()
        }
        const read = readClauseSelect(tokens, issues)
        return read ? { value: { clauses: [{ ...read.clause, name: 'a' }] }, issues } : tooCustom()
    } catch (error) {
        if (error instanceof SqlReadError) {
            issues.push(error.message)
            return tooCustom()
        }
        throw error
    }
}

const dedupeNames = (clauses: BuilderClause[]): BuilderClause[] => {
    const seen = new Set<string>()
    return clauses.map((clause, index) => {
        const name = /^[a-z_][a-z0-9_]*$/.test(clause.name) && !seen.has(clause.name) ? clause.name : clauseAlias(index)
        seen.add(name)
        return { ...clause, name }
    })
}

/** The formula shape builderToSql writes: an outer formula over per-clause sums of a UNION ALL. Null when it is not that shape. */
function readFormula(tokens: Token[], issues: string[]): ConversionResult<BuilderQuery> | null {
    const outer = parseSelect(tokens)
    if (outer.source?.kind !== 'subquery') {
        return null
    }
    const middle = parseSelect(outer.source.tokens)
    if (middle.source?.kind !== 'subquery') {
        return null
    }
    const branches = splitTopLevel(middle.source.tokens, unionSeparator)
    const sums = middle.columns.filter((column) => /^sum\([a-z_][a-z0-9_]*\)$/i.test(canon(column.expr)))
    if (branches.length < 1 || sums.length === 0 || sums.length !== branches.length) {
        return null
    }
    const valueColumn = outer.columns.find((column) => column.alias?.toLowerCase() === 'value')
    if (!valueColumn) {
        return null
    }
    const clauses: BuilderClause[] = []
    for (const branch of branches) {
        const select = parseSelect(branch)
        const own = select.columns.find((column) => canon(column.expr).toLowerCase() === 'value' && column.alias)
        if (!own || select.source?.kind !== 'subquery') {
            return null
        }
        const read = readClauseSelect(select.source.tokens, issues)
        if (!read) {
            return { value: null, issues }
        }
        clauses.push({ ...read.clause, name: own.alias!.toLowerCase() })
    }
    const formulaTokens = valueColumn.expr.map((token) => token.value)
    if (!formulaTokens.every((token) => FORMULA_TOKEN.test(token.toLowerCase()))) {
        issues.push(`The formula "${canon(valueColumn.expr)}" uses SQL the builder formula does not support.`)
        return { value: null, issues }
    }
    const formula = formulaTokens.join(' ').toLowerCase().replace(/\( /g, '(').replace(/ \)/g, ')')
    return { value: { clauses, formula }, issues }
}
