import { ChartAxis } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

export interface QueryConfig {
    dateFrom: string
    dateTo: string
    requestNameBreakdownEnabled: boolean
    requestNameFilter: string[]
}

const formatSelectColumns = (columns: (string | false | null | undefined)[]): string =>
    columns.filter(Boolean).join(',\n        ')

const formatCommaSeparated = (items: (string | false | null | undefined)[]): string =>
    items.filter(Boolean).join(', ')

const createRequestNameFilterClause = (requestNameFilter: string[]): string => {
    if (requestNameFilter.length === 0) {
        return ''
    }

    return hogql`and has(${requestNameFilter}, name)`
}

export const createExpensiveQueriesColumns = (requestNameBreakdownEnabled: boolean): ChartAxis[] => {
    const baseColumns = [
        {
            column: 'query_start_time',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query_duration_ms',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'read_tb',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'cpu_sec',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'created_by',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
    ]

    return requestNameBreakdownEnabled
        ? [
              ...baseColumns,
              {
                  column: 'name',
                  settings: { formatting: { prefix: '', suffix: '' } },
              },
          ]
        : baseColumns
}

export const createLast20QueriesColumns = (requestNameBreakdownEnabled: boolean): ChartAxis[] => {
    const baseColumns = [
        {
            column: 'finished_at',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query_duration_ms',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'created_by',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
    ]

    return requestNameBreakdownEnabled
        ? [
              ...baseColumns,
              {
                  column: 'name',
                  settings: { formatting: { prefix: '', suffix: '' } },
              },
          ]
        : baseColumns
}

export const createFailedQueriesColumns = (): ChartAxis[] => {
    return [
        {
            column: 'finished_at',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query_id',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'endpoint',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query_duration_ms',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'name',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'read_tb',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'human_readable_read_size',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'cpu_sec',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'memory_usage',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'status',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'exception_code',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'exception_name',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
    ]
}

export const createApiQueriesCountQuery = ({
    dateFrom,
    dateTo,
    requestNameBreakdownEnabled,
    requestNameFilter,
}: QueryConfig): string => {
    const selectColumns = formatSelectColumns([
        'event_date',
        requestNameBreakdownEnabled && 'name',
        'count(1) as number_of_queries',
    ])
    const groupByColumns = formatCommaSeparated(['event_date', requestNameBreakdownEnabled && 'name'])
    const orderByColumns = formatCommaSeparated(['event_date asc', requestNameBreakdownEnabled && 'name asc'])
    const requestNameFilterClause = createRequestNameFilterClause(requestNameFilter)

    return hogql`
        select
            ${hogql.raw(selectColumns)}
        from query_log
        where
            is_personal_api_key_request
            and event_date >= ${dateFrom}
            and event_date <= ${dateTo}
            ${hogql.raw(requestNameFilterClause)}
        group by ${hogql.raw(groupByColumns)}
        order by ${hogql.raw(orderByColumns)}
    `
}

export const createApiReadTbQuery = ({
    dateFrom,
    dateTo,
    requestNameBreakdownEnabled,
    requestNameFilter,
}: QueryConfig): string => {
    const selectColumns = formatSelectColumns([
        'event_date',
        requestNameBreakdownEnabled && 'name',
        'sum(read_bytes) / 1e12 as read_tb',
    ])
    const groupByColumns = formatCommaSeparated(['event_date', requestNameBreakdownEnabled && 'name'])
    const orderByColumns = formatCommaSeparated(['event_date asc', requestNameBreakdownEnabled && 'name asc'])
    const requestNameFilterClause = createRequestNameFilterClause(requestNameFilter)

    return hogql`
        select
            ${hogql.raw(selectColumns)}
        from query_log
        where
            is_personal_api_key_request
            and event_date >= ${dateFrom}
            and event_date <= ${dateTo}
            ${hogql.raw(requestNameFilterClause)}
        group by ${hogql.raw(groupByColumns)}
        order by ${hogql.raw(orderByColumns)}
    `
}

export const createApiCpuSecondsQuery = ({
    dateFrom,
    dateTo,
    requestNameBreakdownEnabled,
    requestNameFilter,
}: QueryConfig): string => {
    const selectColumns = formatSelectColumns([
        'event_date',
        requestNameBreakdownEnabled && 'name',
        'sum(cpu_microseconds) / 1e6 as cpu_sec',
    ])
    const groupByColumns = formatCommaSeparated(['event_date', requestNameBreakdownEnabled && 'name'])
    const orderByColumns = formatCommaSeparated(['event_date asc', requestNameBreakdownEnabled && 'name asc'])
    const requestNameFilterClause = createRequestNameFilterClause(requestNameFilter)

    return hogql`
        select
            ${hogql.raw(selectColumns)}
        from query_log
        where
            is_personal_api_key_request
            and event_date >= ${dateFrom}
            and event_date <= ${dateTo}
            ${hogql.raw(requestNameFilterClause)}
        group by ${hogql.raw(groupByColumns)}
        order by ${hogql.raw(orderByColumns)}
    `
}

export const createApiQueriesPerKeyQuery = ({ dateFrom, dateTo }: QueryConfig): string => {
    return hogql`
        select
            event_date,
            api_key_label,
            count(1) as total_queries
        from query_log
        where
            event_date >= ${dateFrom}
            and event_date <= ${dateTo}
            and is_personal_api_key_request
        group by event_date, api_key_label
        order by event_date
    `
}

export const createLast20QueriesQuery = ({
    dateFrom,
    dateTo,
    requestNameBreakdownEnabled,
    requestNameFilter,
}: QueryConfig): string => {
    const selectColumns = formatSelectColumns([
        'event_time as finished_at',
        requestNameBreakdownEnabled && 'name',
        'query',
        'query_duration_ms',
        'api_key_label',
        'created_by',
    ])
    const requestNameFilterClause = createRequestNameFilterClause(requestNameFilter)

    return hogql`
        select
            ${hogql.raw(selectColumns)}
        from query_log
        where
            is_personal_api_key_request
            and event_date >= ${dateFrom}
            and event_date <= ${dateTo}
            ${hogql.raw(requestNameFilterClause)}
        order by event_time desc
        limit 20
    `
}

export const createExpensiveQueriesQuery = ({
    dateFrom,
    dateTo,
    requestNameBreakdownEnabled,
    requestNameFilter,
}: QueryConfig): string => {
    const selectColumns = formatSelectColumns([
        'query_start_time',
        requestNameBreakdownEnabled && 'name',
        'query',
        'query_duration_ms',
        'api_key_label',
        'read_bytes / 1e12 as read_tb',
        'formatReadableSize(read_bytes) as human_readable_read_size',
        'cpu_microseconds / 1e6 as cpu_sec',
        'memory_usage',
        'created_by',
    ])
    const requestNameFilterClause = createRequestNameFilterClause(requestNameFilter)
    const orderByColumns = formatCommaSeparated(['read_tb desc', 'event_time desc'])

    return hogql`
        select
            ${hogql.raw(selectColumns)}
        from query_log
        where
            is_personal_api_key_request
            and event_date >= ${dateFrom}
            and event_date <= ${dateTo}
            ${hogql.raw(requestNameFilterClause)}
        order by ${hogql.raw(orderByColumns)}
        limit 25
    `
}

export const createFailedQueriesQuery = ({ dateFrom, dateTo }: QueryConfig): string => {
    const selectColumns = formatSelectColumns([
        'event_time as finished_at',
        'query_id',
        'endpoint',
        'query',
        'query_duration_ms',
        'name',
        'read_bytes / 1e12 as read_tb',
        'formatReadableSize(read_bytes) as human_readable_read_size',
        'cpu_microseconds / 1e6 as cpu_sec',
        'memory_usage',
        'status',
        'exception_code',
        'exception_name',
    ])
    const orderByColumns = formatCommaSeparated(['read_tb desc', 'event_time desc'])

    return hogql`
        select
            ${hogql.raw(selectColumns)}
        from query_log
        where
            is_personal_api_key_request
            and exception_code != 0
            and event_date >= ${dateFrom}
            and event_date <= ${dateTo}
        order by ${hogql.raw(orderByColumns)}
        limit 25
    `
}
