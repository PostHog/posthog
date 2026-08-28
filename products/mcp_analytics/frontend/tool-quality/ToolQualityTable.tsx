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
    Pagination,
    PaginationButton,
    PaginationContent,
    PaginationEllipsis,
    PaginationItem,
    PaginationNext,
    PaginationPrevious,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    getPaginationRange,
} from '@posthog/quill-primitives'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { formatPercentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { formatMs, formatNumber } from '../dashboard/formatters'
import {
    type SortState,
    type ToolQualitySortColumn,
    TOOL_QUALITY_PAGE_SIZE,
    mcpAnalyticsToolQualityLogic,
    mcpToolReportUrl,
} from '../mcpAnalyticsToolQualityLogic'

const DESTRUCTIVE_ERROR_PCT = 5

interface ColumnSpec {
    key: ToolQualitySortColumn
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
    loading,
    onSort,
}: {
    column: ColumnSpec
    sort: SortState
    loading: boolean
    onSort: (column: ToolQualitySortColumn, direction: 'ASC' | 'DESC') => void
}): JSX.Element {
    const isSorted = sort.column === column.key
    const nextDirection = isSorted && sort.direction === 'DESC' ? 'ASC' : 'DESC'
    const head = (
        <button
            type="button"
            disabled={loading}
            onClick={() => onSort(column.key, nextDirection)}
            className="inline-flex cursor-pointer select-none items-center gap-1"
        >
            {column.label}
            {isSorted ? <span className="text-[9px]">{sort.direction === 'DESC' ? '▼' : '▲'}</span> : null}
        </button>
    )
    return (
        <TableHead
            align={column.align}
            aria-sort={isSorted ? (sort.direction === 'DESC' ? 'descending' : 'ascending') : 'none'}
        >
            {column.tooltip ? <Tooltip title={column.tooltip}>{head}</Tooltip> : head}
        </TableHead>
    )
}

function ToolRows(): JSX.Element {
    const { toolRows, toolRowsPageLoading, selectedTool, dateFilter, pinnedInterval } =
        useValues(mcpAnalyticsToolQualityLogic)
    const { setSelectedTool } = useActions(mcpAnalyticsToolQualityLogic)

    if (toolRowsPageLoading) {
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
    if (toolRows.length === 0) {
        return <TableEmpty className="py-6 text-secondary">No tool calls match the current filters.</TableEmpty>
    }
    return (
        <TableBody>
            {toolRows.map((row) => (
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
                            render={<LinkPrimitive to={mcpToolReportUrl(row.tool, dateFilter, pinnedInterval)} />}
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
    const { toolQualitySort, toolQualityPageIndex, toolRows, toolRowsPageLoading, toolRowsTotalCount, searchTerm } =
        useValues(mcpAnalyticsToolQualityLogic)
    const { setToolQualitySort, setToolQualityPageIndex, setSearchTerm } = useActions(mcpAnalyticsToolQualityLogic)
    const pageCount = Math.max(Math.ceil(toolRowsTotalCount / TOOL_QUALITY_PAGE_SIZE), 1)
    const pageRange = getPaginationRange(pageCount, toolQualityPageIndex)
    const firstRow = toolRowsTotalCount === 0 ? 0 : toolQualityPageIndex * TOOL_QUALITY_PAGE_SIZE + 1
    const lastRow = Math.min(firstRow + toolRows.length - 1, toolRowsTotalCount)

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
                                loading={toolRowsPageLoading}
                                onSort={setToolQualitySort}
                            />
                        ))}
                        <TableHead />
                    </TableRow>
                </TableHeader>
                <ToolRows />
            </Table>
            {!toolRowsPageLoading && toolRowsTotalCount > 0 && (
                <CardFooter className="flex flex-row flex-wrap items-center justify-between gap-2 border-t border-border">
                    <Text size="xs" variant="muted" render={<span />} className="tabular-nums">
                        {firstRow}-{lastRow} of {pluralize(toolRowsTotalCount, 'tool')}
                    </Text>
                    {pageCount > 1 ? (
                        <Pagination className="w-auto">
                            <PaginationContent>
                                <PaginationItem>
                                    <PaginationPrevious
                                        disabled={toolQualityPageIndex === 0}
                                        onClick={() => setToolQualityPageIndex(toolQualityPageIndex - 1)}
                                        data-attr="mcp-tool-quality-page-previous"
                                    />
                                </PaginationItem>
                                {pageRange.map((item, index) =>
                                    item === 'ellipsis' ? (
                                        <PaginationItem key={`ellipsis-${index}`}>
                                            <PaginationEllipsis />
                                        </PaginationItem>
                                    ) : (
                                        <PaginationItem key={item}>
                                            <PaginationButton
                                                isActive={item === toolQualityPageIndex}
                                                aria-label={`Go to page ${item + 1}`}
                                                onClick={() => setToolQualityPageIndex(item)}
                                                data-attr="mcp-tool-quality-page"
                                            >
                                                {item + 1}
                                            </PaginationButton>
                                        </PaginationItem>
                                    )
                                )}
                                <PaginationItem>
                                    <PaginationNext
                                        disabled={toolQualityPageIndex === pageCount - 1}
                                        onClick={() => setToolQualityPageIndex(toolQualityPageIndex + 1)}
                                        data-attr="mcp-tool-quality-page-next"
                                    />
                                </PaginationItem>
                            </PaginationContent>
                        </Pagination>
                    ) : null}
                </CardFooter>
            )}
        </Card>
    )
}
