import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { LemonSkeleton } from '@posthog/lemon-ui'
import {
    Badge,
    Button,
    Card,
    CardFooter,
    CardHeader,
    CardTitle,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill-primitives'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { formatPercentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { formatMs, formatNumber } from '../dashboard/formatters'
import { type SortState, type ToolQualityRow, mcpAnalyticsToolQualityLogic } from '../mcpAnalyticsToolQualityLogic'

const DESTRUCTIVE_ERROR_PCT = 5

// LIMIT in tool_quality.sql — when the fetched set hits this, more tools may exist.
const TOOL_ROW_LIMIT = 200

function formatToolCount(filtered: number, total: number): string {
    if (filtered < total) {
        return `Showing ${filtered} of ${pluralize(total, 'tool')}`
    }
    if (total >= TOOL_ROW_LIMIT) {
        return `Showing first ${pluralize(total, 'tool')}`
    }
    return pluralize(total, 'tool')
}

interface ColumnSpec {
    key: keyof ToolQualityRow
    label: string
    align?: 'left' | 'right'
    tooltip?: string
}

const SORTABLE_COLUMNS: ColumnSpec[] = [
    { key: 'total_calls', label: 'Calls', align: 'right', tooltip: 'Total number of times this tool was called' },
    {
        key: 'error_rate_pct',
        label: 'Error rate',
        align: 'right',
        tooltip: 'Percentage of calls that returned $mcp_is_error = true',
    },
    { key: 'p50_duration_ms', label: 'p50', align: 'right', tooltip: 'Median $mcp_duration_ms' },
    { key: 'p95_duration_ms', label: 'p95', align: 'right', tooltip: '95th-percentile $mcp_duration_ms' },
    { key: 'p99_duration_ms', label: 'p99', align: 'right', tooltip: '99th-percentile $mcp_duration_ms' },
    { key: 'users', label: 'Users', align: 'right', tooltip: 'Unique users who invoked this tool' },
    { key: 'sessions', label: 'Sessions', align: 'right', tooltip: 'Unique sessions where this tool was called' },
    { key: 'last_seen', label: 'Last seen' },
]

// Tool column + every sortable column + the trailing "Full report" action, for the skeleton-row colSpan
const COLUMN_COUNT = SORTABLE_COLUMNS.length + 2

function ErrorRateBadge({ pct }: { pct: number }): JSX.Element {
    if (pct <= 0) {
        return <Badge variant="success">0%</Badge>
    }
    return (
        <Badge variant={pct >= DESTRUCTIVE_ERROR_PCT ? 'destructive' : 'warning'}>
            {formatPercentage(pct, { compact: true })}
        </Badge>
    )
}

function SortableHead({
    column,
    sort,
    onSort,
}: {
    column: ColumnSpec
    sort: SortState
    onSort: (column: string, direction: 'ASC' | 'DESC') => void
}): JSX.Element {
    const isSorted = sort.column === column.key
    const nextDirection = isSorted && sort.direction === 'DESC' ? 'ASC' : 'DESC'
    const head = (
        <button
            type="button"
            onClick={() => onSort(column.key, nextDirection)}
            className="inline-flex cursor-pointer select-none items-center gap-1"
        >
            {column.label}
            {isSorted ? <span className="text-[9px]">{sort.direction === 'DESC' ? '▼' : '▲'}</span> : null}
        </button>
    )
    return (
        <TableHead align={column.align}>
            {column.tooltip ? <Tooltip title={column.tooltip}>{head}</Tooltip> : head}
        </TableHead>
    )
}

function ToolRows(): JSX.Element {
    const { filteredRows, toolRowsLoading, selectedTool } = useValues(mcpAnalyticsToolQualityLogic)
    const { setSelectedTool } = useActions(mcpAnalyticsToolQualityLogic)

    if (toolRowsLoading && filteredRows.length === 0) {
        return (
            <TableBody>
                <TableRow>
                    <TableCell colSpan={COLUMN_COUNT}>
                        <div className="space-y-2 py-1">
                            {Array.from({ length: 6 }).map((_, i) => (
                                <LemonSkeleton key={i} className="h-3.5 w-full" />
                            ))}
                        </div>
                    </TableCell>
                </TableRow>
            </TableBody>
        )
    }
    if (filteredRows.length === 0) {
        return <TableEmpty className="py-6 text-secondary">No tool calls match the current filters.</TableEmpty>
    }
    return (
        <TableBody>
            {filteredRows.map((row) => (
                <TableRow
                    key={row.tool}
                    data-state={row.tool === selectedTool ? 'selected' : undefined}
                    className="cursor-pointer"
                    onClick={() => setSelectedTool(row.tool === selectedTool ? null : row.tool)}
                    data-attr="mcp-tool-quality-row"
                >
                    <TableCell expand>
                        <span className="font-mono">{row.tool}</span>
                    </TableCell>
                    <TableCell align="right">{formatNumber(row.total_calls)}</TableCell>
                    <TableCell align="right">
                        <ErrorRateBadge pct={row.error_rate_pct} />
                    </TableCell>
                    <TableCell align="right">{formatMs(row.p50_duration_ms)}</TableCell>
                    <TableCell align="right">{formatMs(row.p95_duration_ms)}</TableCell>
                    <TableCell align="right">{formatMs(row.p99_duration_ms)}</TableCell>
                    <TableCell align="right">{formatNumber(row.users)}</TableCell>
                    <TableCell align="right">{formatNumber(row.sessions)}</TableCell>
                    <TableCell className="whitespace-nowrap">
                        <TZLabel time={row.last_seen} />
                    </TableCell>
                    <TableCell align="right">
                        <Button
                            variant="outline"
                            size="sm"
                            render={<LinkPrimitive to={urls.mcpAnalyticsTool(row.tool)} />}
                            onClick={(e) => e.stopPropagation()}
                            data-attr="mcp-tool-quality-full-report"
                        >
                            Full report
                        </Button>
                    </TableCell>
                </TableRow>
            ))}
        </TableBody>
    )
}

export function ToolQualityTable(): JSX.Element {
    const { toolQualitySort, toolRows, filteredRows, toolRowsLoading, searchTerm } =
        useValues(mcpAnalyticsToolQualityLogic)
    const { setToolQualitySort, setSearchTerm } = useActions(mcpAnalyticsToolQualityLogic)

    return (
        <Card size="sm" className="gap-0">
            <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
                <CardTitle>All tools</CardTitle>
                <InputGroup className="w-[220px]">
                    <InputGroupAddon align="inline-start">
                        <InputGroupText>
                            <IconSearch />
                        </InputGroupText>
                    </InputGroupAddon>
                    <InputGroupInput
                        type="search"
                        placeholder="Search tools"
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        data-attr="mcp-tool-quality-search"
                    />
                </InputGroup>
            </CardHeader>
            <Table fullWidth stickyHeader className="max-h-[44rem]">
                <TableHeader>
                    <TableRow>
                        <TableHead expand>Tool</TableHead>
                        {SORTABLE_COLUMNS.map((column) => (
                            <SortableHead
                                key={column.key}
                                column={column}
                                sort={toolQualitySort}
                                onSort={setToolQualitySort}
                            />
                        ))}
                        <TableHead />
                    </TableRow>
                </TableHeader>
                <ToolRows />
            </Table>
            {!toolRowsLoading && toolRows.length > 0 && (
                <CardFooter className="border-t border-border py-2 text-xs text-secondary">
                    {formatToolCount(filteredRows.length, toolRows.length)}
                </CardFooter>
            )}
        </Card>
    )
}
