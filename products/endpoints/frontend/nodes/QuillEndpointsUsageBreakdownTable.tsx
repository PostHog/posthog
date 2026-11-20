import type { ColumnDef } from '@tanstack/react-table'
import { useMemo } from 'react'

import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    DataTable,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, humanizeBytes } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { EndpointsUsageTableQuery, EndpointsUsageTableQueryResponse } from '~/queries/schema/schema-general'

import { useEndpointsUsageQuery } from './useEndpointsUsageQuery'

interface BreakdownRow {
    endpoint: string
    requests: number
    bytes_read: number
    cpu_seconds: number
    avg_query_duration_ms: number
    error_rate: number
}

// The query returns each row as an array in this order.
const ROW_KEYS: (keyof BreakdownRow)[] = [
    'endpoint',
    'requests',
    'bytes_read',
    'cpu_seconds',
    'avg_query_duration_ms',
    'error_rate',
]

function toRow(values: unknown): BreakdownRow {
    const cells = values as unknown[]
    return Object.fromEntries(ROW_KEYS.map((key, index) => [key, cells[index]])) as unknown as BreakdownRow
}

export function QuillEndpointsUsageBreakdownTable({
    query,
    activeEndpointNames,
}: {
    query: EndpointsUsageTableQuery
    activeEndpointNames: Set<string>
}): JSX.Element {
    const { response, responseLoading, responseError, retry } =
        useEndpointsUsageQuery<EndpointsUsageTableQueryResponse>(query)
    const rows = useMemo(() => (response?.results ?? []).map(toRow), [response])

    const columns = useMemo<ColumnDef<BreakdownRow>[]>(
        () => [
            {
                accessorKey: 'endpoint',
                header: 'Endpoint',
                meta: { expand: true },
                cell: ({ row }) => {
                    const name = row.original.endpoint
                    return activeEndpointNames.has(name) ? (
                        <Button
                            variant="link-foreground"
                            size="sm"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.endpoint(name)} />}
                        >
                            {name}
                        </Button>
                    ) : (
                        <Text variant="muted">{name} (deleted)</Text>
                    )
                },
            },
            {
                accessorKey: 'requests',
                header: 'Executions',
                meta: { align: 'right' },
                sortDescFirst: true,
                cell: ({ row }) => humanFriendlyNumber(row.original.requests),
            },
            {
                accessorKey: 'bytes_read',
                header: 'Bytes read',
                meta: { align: 'right' },
                sortDescFirst: true,
                cell: ({ row }) => humanizeBytes(row.original.bytes_read),
            },
            {
                accessorKey: 'cpu_seconds',
                header: 'CPU time',
                meta: { align: 'right' },
                sortDescFirst: true,
                cell: ({ row }) => humanFriendlyDuration(row.original.cpu_seconds),
            },
            {
                accessorKey: 'avg_query_duration_ms',
                header: 'Avg query duration',
                meta: { align: 'right' },
                sortDescFirst: true,
                cell: ({ row }) => humanFriendlyDuration(row.original.avg_query_duration_ms / 1000),
            },
            {
                accessorKey: 'error_rate',
                header: 'Error rate',
                meta: { align: 'right' },
                sortDescFirst: true,
                cell: ({ row }) => `${(row.original.error_rate * 100).toFixed(2)}%`,
            },
        ],
        [activeEndpointNames]
    )

    return (
        <Card size="sm" className="min-w-0" data-attr="endpoints-usage-breakdown">
            <CardHeader>
                <CardTitle role="heading" aria-level={3}>
                    Endpoints breakdown
                </CardTitle>
                {response?.hasMore && (
                    <CardDescription>Showing the {rows.length} endpoints with the most executions.</CardDescription>
                )}
            </CardHeader>
            <CardContent>
                {responseLoading ? (
                    <Skeleton className="h-48 w-full" />
                ) : responseError ? (
                    <div className="flex flex-col items-center gap-2 py-4">
                        <Text variant="muted">Could not load this table.</Text>
                        <Button variant="outline" onClick={retry}>
                            Try again
                        </Button>
                    </div>
                ) : (
                    <DataTable
                        columns={columns}
                        data={rows}
                        pageSize={20}
                        fullWidth
                        size="sm"
                        getRowId={(row) => row.endpoint}
                        empty={<Text variant="muted">No data available for this period</Text>}
                    />
                )}
            </CardContent>
        </Card>
    )
}
