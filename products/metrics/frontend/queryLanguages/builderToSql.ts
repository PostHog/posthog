import type { MetricsAttributeScope } from '~/queries/schema/schema-general'

import { type BuilderClause, type BuilderQuery, type ConversionResult, normalizeLabelKey } from './types'

/**
 * Builder → SQL for a SQL metrics insight.
 *
 * The SQL follows the SQL-mode contract: a `time` column, a numeric `value` column, and one column
 * per label. `{date_from}`, `{date_to}`, `{interval}` and `{interval_seconds}` are filled in by the
 * backend, so dashboard date filters still apply. Each clause mirrors the query the builder engine
 * runs (products/metrics/backend/metric_query_runner.py): the last value of each series per bucket
 * for gauges, per-sample deltas with counter-reset handling for rate/increase, and the same bucket
 * interpolation for histogram quantiles. `sqlToBuilder` reads this exact shape back.
 */

export const SQL_RESERVED_COLUMNS = new Set(['time', 'value', 'clause'])

export const quoteSqlString = (value: string): string => `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`

const SAFE_IDENTIFIER = /^[a-zA-Z_][a-zA-Z0-9_]*$/
export const quoteSqlIdentifier = (name: string): string =>
    SAFE_IDENTIFIER.test(name) ? name : `\`${name.replace(/\\/g, '\\\\').replace(/`/g, '\\`')}\``

export function attributeSqlField(key: string, scope: MetricsAttributeScope | undefined): string {
    const normalized = normalizeLabelKey(key)
    if (normalized === 'service_name') {
        return 'service_name'
    }
    const quoted = quoteSqlString(key)
    if (scope === 'resource') {
        return `arrayElement(resource_attributes, ${quoted})`
    }
    if (scope === 'attribute') {
        return `arrayElement(attributes, ${quoted})`
    }
    return `if(arrayElement(resource_attributes, ${quoted}) != '', arrayElement(resource_attributes, ${quoted}), arrayElement(attributes, ${quoted}))`
}

function filterCondition(filter: NonNullable<BuilderClause['filters']>[number]): string {
    const field = attributeSqlField(filter.key, filter.scope)
    const value = quoteSqlString(filter.value)
    switch (filter.op) {
        case 'eq':
            return `${field} = ${value}`
        case 'neq':
            return `${field} != ${value}`
        case 'regex':
            return `match(${field}, ${value})`
        case 'not_regex':
            return `NOT match(${field}, ${value})`
    }
}

const indent = (text: string, spaces: number): string =>
    text
        .split('\n')
        .map((line) => (line ? ' '.repeat(spaces) + line : line))
        .join('\n')

export const labelColumn = (key: string): string => quoteSqlIdentifier(normalizeLabelKey(key))

interface ClauseSqlOptions {
    /** Label columns every clause of the query must expose, in order; clauses fill missing ones with ''. */
    labelKeys: string[]
    /** Adds a `clause` label column with this alias, to keep the series of a multi-series query apart. */
    clauseLabel?: string
    orderByTime: boolean
}

function pointsWhere(clause: BuilderClause, from: string): string[] {
    const metricName = quoteSqlString(clause.metricName)
    const conditions = [`metric_name = ${metricName}`]
    if (clause.metricType) {
        conditions.push(`metric_type = ${quoteSqlString(clause.metricType)}`)
    }
    conditions.push(`timestamp >= ${from}`, 'timestamp < {date_to}')
    if (clause.filters?.length) {
        const seriesFilters = [
            `metric_name = ${metricName}`,
            'last_seen >= {date_from} - toIntervalHour(1)',
            ...clause.filters.map(filterCondition),
        ]
        conditions.push(
            [
                'series_fingerprint IN (',
                '    SELECT series_fingerprint',
                '    FROM posthog.metric_series',
                `    WHERE ${seriesFilters.join('\n        AND ')}`,
                ')',
            ].join('\n')
        )
    }
    return conditions
}

function whereBlock(conditions: string[]): string {
    const lines = conditions.map((condition, i) => (i === 0 ? condition : `AND ${condition}`).replace(/\n/g, '\n    '))
    return `WHERE ${lines.join('\n    ')}`
}

function groupJoin(clause: BuilderClause): string | null {
    const groupBy = clause.groupBy ?? []
    if (!groupBy.length) {
        return null
    }
    const columns = groupBy.map(
        (group, index) => `any(toString(${attributeSqlField(group.key, group.scope)})) AS group_${index}`
    )
    return [
        'LEFT JOIN (',
        '    SELECT',
        `        ${['series_fingerprint', ...columns].join(',\n        ')}`,
        '    FROM posthog.metric_series',
        `    WHERE metric_name = ${quoteSqlString(clause.metricName)}`,
        '        AND last_seen >= {date_from} - toIntervalHour(1)',
        '    GROUP BY series_fingerprint',
        ') AS ser ON s.series_fingerprint = ser.series_fingerprint',
    ].join('\n')
}

function labelSelect(clause: BuilderClause, options: ClauseSqlOptions): { columns: string[]; groupBy: string[] } {
    const own = (clause.groupBy ?? []).map((group) => normalizeLabelKey(group.key))
    const columns: string[] = []
    const groupBy: string[] = []
    if (options.clauseLabel) {
        columns.push(`${quoteSqlString(options.clauseLabel)} AS clause`)
    }
    for (const key of options.labelKeys) {
        const index = own.indexOf(key)
        columns.push(`${index >= 0 ? `ser.group_${index}` : "''"} AS ${quoteSqlIdentifier(key)}`)
        if (index >= 0) {
            groupBy.push(quoteSqlIdentifier(key))
        }
    }
    return { columns, groupBy }
}

const SIMPLE_VALUE: Record<string, (q: number | undefined) => string> = {
    sum: () => 'sum(s.series_value)',
    avg: () => 'avg(s.series_value)',
    min: () => 'min(s.series_value)',
    max: () => 'max(s.series_value)',
    // A float, so a UNION with the other series' values has one column type.
    count: () => 'toFloat(count())',
    quantile: (q) => `quantile(${q ?? 0.95})(s.series_value)`,
}

function simpleClauseSql(clause: BuilderClause, options: ClauseSqlOptions): string {
    const labels = labelSelect(clause, options)
    const join = groupJoin(clause)
    const lines = [
        'SELECT',
        `    ${['s.time AS time', ...labels.columns, `${SIMPLE_VALUE[clause.aggregation](clause.quantile)} AS value`].join(',\n    ')}`,
        'FROM (',
        '    SELECT',
        '        toStartOfInterval(timestamp, {interval}) AS time,',
        '        series_fingerprint,',
        '        argMax(value, timestamp) AS series_value',
        '    FROM posthog.metrics',
        indent(whereBlock(pointsWhere(clause, '{date_from}')), 4),
        '    GROUP BY time, series_fingerprint',
        ') AS s',
        ...(join ? [join] : []),
        `GROUP BY ${['time', ...labels.groupBy].join(', ')}`,
        ...(options.orderByTime ? ['ORDER BY time'] : []),
    ]
    return lines.join('\n')
}

const COUNTER_LOOKBACK_FROM = '{date_from} - toIntervalSecond(greatest({interval_seconds}, 300))'

function counterClauseSql(clause: BuilderClause, options: ClauseSqlOptions): string {
    const labels = labelSelect(clause, options)
    const join = groupJoin(clause)
    const value = clause.aggregation === 'rate' ? 'sum(s.contribution) / {interval_seconds}' : 'sum(s.contribution)'
    const lines = [
        'SELECT',
        `    ${['toStartOfInterval(s.sample_timestamp, {interval}) AS time', ...labels.columns, `${value} AS value`].join(',\n    ')}`,
        'FROM (',
        '    SELECT',
        '        timestamp AS sample_timestamp,',
        '        series_fingerprint,',
        '        multiIf(',
        "            aggregation_temporality = 'delta', value,",
        '            isNull(prev_value), NULL,',
        '            value >= assumeNotNull(prev_value), value - assumeNotNull(prev_value),',
        '            value',
        '        ) AS contribution',
        '    FROM (',
        '        SELECT',
        '            timestamp,',
        '            series_fingerprint,',
        '            value,',
        '            aggregation_temporality,',
        '            lagInFrame(toNullable(value)) OVER (',
        '                PARTITION BY series_fingerprint',
        '                ORDER BY timestamp ASC',
        '                ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING',
        '            ) AS prev_value',
        '        FROM posthog.metrics',
        indent(whereBlock(pointsWhere(clause, COUNTER_LOOKBACK_FROM)), 8),
        '    )',
        ') AS s',
        ...(join ? [join] : []),
        'WHERE s.sample_timestamp >= {date_from}',
        `GROUP BY ${['time', ...labels.groupBy].join(', ')}`,
        'HAVING isNotNull(value)',
        ...(options.orderByTime ? ['ORDER BY time'] : []),
    ]
    return lines.join('\n')
}

function histogramClauseSql(clause: BuilderClause, options: ClauseSqlOptions): string {
    const labels = labelSelect(clause, options)
    const join = groupJoin(clause)
    const labelNames = [...(options.clauseLabel ? ['clause'] : []), ...options.labelKeys.map(quoteSqlIdentifier)]
    const q = clause.quantile ?? 0.95
    // Interpolates inside the bucket that holds the rank, as _histogram_quantile does in the engine.
    const quantile = [
        'if(',
        '    idx > length(bounds),',
        '    bounds[length(bounds)],',
        '    if(idx > 1, bounds[idx - 1], least(0.0, bounds[1]))',
        '        + (bounds[idx] - if(idx > 1, bounds[idx - 1], least(0.0, bounds[1])))',
        '        * (rank - (cumulative[idx] - counts[idx])) / counts[idx]',
        ')',
    ].join('\n')
    const lines = [
        'SELECT',
        `    ${['time', ...labelNames, `${indent(quantile, 4).trimStart()} AS value`].join(',\n    ')}`,
        'FROM (',
        '    SELECT',
        `        ${[
            'time',
            ...labelNames,
            'bounds',
            'counts',
            'arrayCumSum(counts) AS cumulative',
            `${q} * arraySum(counts) AS rank`,
            'arrayFirstIndex(c -> c >= rank, cumulative) AS idx',
        ].join(',\n        ')}`,
        '    FROM (',
        '        SELECT',
        `            ${[
            'toStartOfInterval(s.sample_timestamp, {interval}) AS time',
            ...labels.columns,
            'any(s.histogram_bounds) AS bounds',
            'arrayMap(x -> ifNull(x, 0.0), sumForEach(s.contribution_counts)) AS counts',
        ].join(',\n            ')}`,
        '        FROM (',
        '            SELECT',
        '                timestamp AS sample_timestamp,',
        '                series_fingerprint,',
        '                histogram_bounds,',
        '                multiIf(',
        "                    aggregation_temporality = 'delta', counts_f,",
        '                    empty(prev_counts), arrayMap(x -> 0.0, counts_f),',
        '                    length(prev_counts) != length(counts_f), counts_f,',
        '                    arrayAll((c, p) -> c >= p, counts_f, prev_counts), arrayMap((c, p) -> c - p, counts_f, prev_counts),',
        '                    counts_f',
        '                ) AS contribution_counts',
        '            FROM (',
        '                SELECT',
        '                    timestamp,',
        '                    series_fingerprint,',
        '                    aggregation_temporality,',
        '                    histogram_bounds,',
        '                    arrayMap(x -> toFloat(x), histogram_counts) AS counts_f,',
        '                    lagInFrame(arrayMap(x -> toFloat(x), histogram_counts)) OVER (',
        '                        PARTITION BY series_fingerprint',
        '                        ORDER BY timestamp ASC',
        '                        ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING',
        '                    ) AS prev_counts',
        '                FROM posthog.metrics',
        indent(whereBlock([...pointsWhere(clause, COUNTER_LOOKBACK_FROM), 'notEmpty(histogram_counts)']), 16),
        '            )',
        '        ) AS s',
        ...(join ? [indent(join, 8)] : []),
        '        WHERE s.sample_timestamp >= {date_from}',
        `        GROUP BY ${['time', ...labels.groupBy].join(', ')}`,
        '    )',
        '    WHERE arraySum(counts) > 0',
        ')',
        ...(options.orderByTime ? ['ORDER BY time'] : []),
    ]
    return lines.join('\n')
}

function clauseSql(clause: BuilderClause, options: ClauseSqlOptions): string {
    switch (clause.aggregation) {
        case 'rate':
        case 'increase':
            return counterClauseSql(clause, options)
        case 'histogram_quantile':
            return histogramClauseSql(clause, options)
        default:
            return simpleClauseSql(clause, options)
    }
}

/** Builder formula → SQL expression over the per-clause value columns. The grammar is the same. */
const formulaToSql = (formula: string): string => formula.replace(/\s+/g, ' ').trim()

export function builderToSql(query: BuilderQuery): ConversionResult<string> {
    const issues: string[] = []
    const clauses = query.clauses.filter((clause) => clause.metricName.trim())
    if (clauses.length === 0) {
        return { value: '', issues }
    }
    const labelKeys: string[] = []
    for (const clause of clauses) {
        for (const group of clause.groupBy ?? []) {
            const key = normalizeLabelKey(group.key)
            if (SQL_RESERVED_COLUMNS.has(key)) {
                issues.push(`The "${key}" group-by has the same name as a result column and is dropped.`)
                continue
            }
            if (!labelKeys.includes(key)) {
                labelKeys.push(key)
            }
        }
    }
    const usable = clauses.map((clause) => ({
        ...clause,
        groupBy: clause.groupBy?.filter((group) => !SQL_RESERVED_COLUMNS.has(normalizeLabelKey(group.key))),
    }))

    if (usable.length === 1 && !query.formula?.trim()) {
        return { value: clauseSql(usable[0], { labelKeys, orderByTime: true }), issues }
    }

    const formula = query.formula?.trim()
    if (!formula) {
        const branches = usable.map((clause) =>
            clauseSql(clause, { labelKeys, clauseLabel: clause.name, orderByTime: false })
        )
        return { value: `${branches.join('\nUNION ALL\n')}`, issues }
    }

    const groupSets = new Set(
        usable.map((clause) => (clause.groupBy ?? []).map((g) => normalizeLabelKey(g.key)).join(','))
    )
    if (groupSets.size > 1) {
        issues.push('The formula mixes series with different group-by labels.')
    }
    const used = usable.filter((clause) => new RegExp(`\\b${clause.name}\\b`).test(formula))
    const unused = usable.filter((clause) => !used.includes(clause))
    if (unused.length) {
        issues.push(
            `Series ${unused.map((clause) => clause.name).join(', ')} ${unused.length > 1 ? 'are' : 'is'} not in the formula and will be removed.`
        )
    }
    const labelColumns = labelKeys.map(quoteSqlIdentifier)
    const branches = used.map((clause) => {
        const values = used.map((other) => `${other === clause ? 'value' : '0'} AS ${other.name}`)
        return [
            'SELECT',
            `    ${['time', ...labelColumns, ...values].join(', ')}`,
            'FROM (',
            indent(clauseSql(clause, { labelKeys, orderByTime: false }), 4),
            ')',
        ].join('\n')
    })
    const lines = [
        'SELECT',
        `    ${['time', ...labelColumns, `${formulaToSql(formula)} AS value`].join(',\n    ')}`,
        'FROM (',
        '    SELECT',
        `        ${['time', ...labelColumns, ...used.map((clause) => `sum(${clause.name}) AS ${clause.name}`)].join(',\n        ')}`,
        '    FROM (',
        indent(branches.join('\nUNION ALL\n'), 8),
        '    )',
        `    GROUP BY ${['time', ...labelColumns].join(', ')}`,
        ')',
        'ORDER BY time',
    ]
    return { value: lines.join('\n'), issues }
}
