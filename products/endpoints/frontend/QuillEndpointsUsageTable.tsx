import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    DataTable,
    type DataTableProps,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, humanizeBytes } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { EndpointsUsageTableQueryResponse } from '~/queries/schema/schema-general'

import { endpointsUsageLogic } from './endpointsUsageLogic'

interface UsageRow {
    endpoint: string
    requests: number
    bytes_read: number
    cpu_seconds: number
    avg_query_duration_ms: number
    error_rate: number
}

const NUMERIC_COLUMNS = ['requests', 'bytes_read', 'cpu_seconds', 'avg_query_duration_ms', 'error_rate'] as const

// The query returns each row as an array in the order of `columns`, so the rows are read by column name.
function toRows(response: EndpointsUsageTableQueryResponse | undefined): UsageRow[] {
    const columns = (response?.columns ?? []) as string[]
    const indexByColumn = new Map(columns.map((column, index) => [column, index]))
    const read = (row: unknown, column: string): unknown =>
        Array.isArray(row) ? row[indexByColumn.get(column) ?? -1] : (row as Record<string, unknown>)?.[column]

    return (response?.results ?? []).map((row) => {
        const usageRow = { endpoint: String(read(row, 'endpoint') ?? '') } as UsageRow
        for (const column of NUMERIC_COLUMNS) {
            usageRow[column] = Number(read(row, column) ?? 0)
        }
        return usageRow
    })
}

// TanStack renders cell functions as components, so their identity must survive re-renders.
const columns: DataTableProps<UsageRow, unknown>['columns'] = [
    {
        accessorKey: 'endpoint',
        header: 'Endpoint',
        meta: { expand: true },
        cell: function EndpointCell({ row }) {
            const { activeEndpointNames } = useValues(endpointsUsageLogic)
            const name = row.original.endpoint
            if (!activeEndpointNames.has(name)) {
                return (
                    <Text size="xs" variant="muted" render={<span />}>
                        {name} (deleted)
                    </Text>
                )
            }
            return (
                <Button
                    variant="link-foreground"
                    size="sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.endpoint(name)} />}
                    data-attr="endpoints-usage-table-endpoint"
                >
                    {name}
                </Button>
            )
        },
    },
    {
        accessorKey: 'requests',
        header: 'Executions',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ getValue }) => humanFriendlyNumber(getValue<number>()),
    },
    {
        accessorKey: 'bytes_read',
        header: 'Bytes read',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ getValue }) => humanizeBytes(getValue<number>()),
    },
    {
        accessorKey: 'cpu_seconds',
        header: 'CPU time',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ getValue }) => humanFriendlyDuration(getValue<number>()),
    },
    {
        accessorKey: 'avg_query_duration_ms',
        header: 'Avg query duration',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ getValue }) => humanFriendlyDuration(getValue<number>() / 1000),
    },
    {
        accessorKey: 'error_rate',
        header: 'Error rate',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ getValue }) => `${(getValue<number>() * 100).toFixed(2)}%`,
    },
]

const PAGE_SIZE = 20

let uniqueNode = 0
export function QuillEndpointsUsageTable(): JSX.Element {
    const { endpointTableQuery } = useValues(endpointsUsageLogic)
    const [key] = useState(() => `EndpointsUsageTable.${uniqueNode++}`)
    const logic = dataNodeLogic({ query: endpointTableQuery, key, dataNodeCollectionId: key })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)

    const rows = useMemo(() => toRows(response as EndpointsUsageTableQueryResponse | undefined), [response])
    const showSkeleton = responseLoading && !response

    return (
        <Card size="sm" flush className="min-w-0" aria-busy={responseLoading}>
            <CardHeader>
                <CardTitle role="heading" aria-level={3}>
                    Endpoints breakdown
                </CardTitle>
                <CardDescription>Usage per endpoint in this period, with the most executed first.</CardDescription>
            </CardHeader>
            <CardContent>
                {showSkeleton ? (
                    <div className="flex flex-col gap-3 px-3 pb-3" role="status">
                        <span className="sr-only">Loading usage per endpoint</span>
                        {[0, 1, 2, 3, 4].map((index) => (
                            <Skeleton key={index} className="h-5 w-full" />
                        ))}
                    </div>
                ) : responseError && rows.length === 0 ? (
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>Couldn't load usage per endpoint</EmptyTitle>
                            <EmptyDescription>{responseError}</EmptyDescription>
                        </EmptyHeader>
                        <EmptyContent>
                            <Button
                                variant="outline"
                                onClick={() => loadData()}
                                data-attr="endpoints-usage-table-retry"
                            >
                                Try again
                            </Button>
                        </EmptyContent>
                    </Empty>
                ) : (
                    <DataTable
                        columns={columns}
                        data={rows}
                        size="sm"
                        fullWidth
                        pageSize={PAGE_SIZE}
                        empty={
                            <Empty>
                                <EmptyHeader>
                                    <EmptyTitle>No executions in this period</EmptyTitle>
                                    <EmptyDescription>
                                        Choose a longer date range or change a filter to see usage per endpoint.
                                    </EmptyDescription>
                                </EmptyHeader>
                            </Empty>
                        }
                    />
                )}
            </CardContent>
        </Card>
    )
}
