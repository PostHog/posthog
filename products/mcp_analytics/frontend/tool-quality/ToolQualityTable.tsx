import { useActions, useValues } from 'kea'

import { IconInfo, IconSort } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardFooter,
    Pagination,
    PaginationButton,
    PaginationContent,
    PaginationEllipsis,
    PaginationItem,
    PaginationNext,
    PaginationPrevious,
    Spinner,
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
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { formatPercentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { DESTRUCTIVE_ERROR_RATE_PCT, formatMs, formatNumber } from '../dashboard/formatters'
import { SkeletonLine } from '../dashboard/SkeletonLine'
import {
    type SortState,
    type ToolQualitySortColumn,
    TOOL_QUALITY_PAGE_SIZE,
    mcpAnalyticsToolQualityLogic,
} from '../mcpAnalyticsToolQualityLogic'
import { mcpFacetsLogic } from '../mcpFacetsLogic'
import { errorRateChange, p95Change } from './qualityChange'
import { QualityChangeMarker } from './QualityChangeMarker'
import { SessionsCell } from './SessionsCell'
import { ToolVolumeCell } from './ToolVolumeCell'
import { TrendCell } from './TrendCell'

const TOOL_BUTTON_CLASS =
    'cursor-pointer rounded-sm text-left font-mono font-semibold text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring'

interface ColumnSpec {
    key: ToolQualitySortColumn
    label: string
    align?: 'left' | 'right'
    tooltip?: string
}

const SORTABLE_COLUMNS: ColumnSpec[] = [
    { key: 'total_calls', label: 'Calls', align: 'right', tooltip: 'Total number of times this tool was called' },
    {
        key: 'trend_score',
        label: 'Trend',
        align: 'right',
        tooltip:
            "Change in calls versus the previous period of the same length. Sorting ranks by growth relative to volume, so small tools don't dominate.",
    },
    {
        key: 'error_rate_pct',
        label: 'Error rate',
        align: 'right',
        tooltip:
            'Percentage of calls marked as failed. An arrow marks a meaningful change versus the previous period, for tools with at least 20 calls in both.',
    },
    {
        key: 'p95_duration_ms',
        label: 'p95',
        align: 'right',
        tooltip:
            '95th-percentile call duration: 95% of calls finished faster than this. An arrow marks a meaningful change versus the previous period, for tools with at least 20 calls in both.',
    },
    { key: 'users', label: 'People', align: 'right', tooltip: 'Unique people who called this tool' },
    {
        key: 'sessions',
        label: 'Sessions',
        align: 'right',
        tooltip: 'Unique sessions where this tool was called, and their share of all sessions in the period',
    },
]

const SKELETON_ROW_WIDTHS = ['70%', '50%', '85%', '40%', '60%', '75%', '45%', '65%']

function ErrorRateBadge({ pct }: { pct: number }): JSX.Element {
    if (pct <= 0) {
        return <Badge variant="success">0%</Badge>
    }
    const badge = (
        <Badge variant={pct >= DESTRUCTIVE_ERROR_RATE_PCT ? 'destructive' : 'warning'}>
            {formatPercentage(pct, { compact: true })}
        </Badge>
    )
    return pct >= DESTRUCTIVE_ERROR_RATE_PCT ? (
        <Tooltip
            title={`${DESTRUCTIVE_ERROR_RATE_PCT}% or more of calls failed. Volume bars turn red in intervals that reach this.`}
        >
            <span tabIndex={0}>{badge}</span>
        </Tooltip>
    ) : (
        badge
    )
}

function VolumeHead(): JSX.Element {
    const { facets } = useValues(mcpFacetsLogic)
    const slowThreshold = facets?.p95 ? ` (${formatMs(Math.round(facets.p95))})` : ''
    return (
        <TableHead align="right">
            <Tooltip
                title={`Calls per interval. A red bar had an error rate of ${DESTRUCTIVE_ERROR_RATE_PCT}% or more. An amber bar was slower than the p95 of all calls${slowThreshold}.`}
            >
                <span tabIndex={0} className="inline-flex items-center gap-1">
                    Volume
                    <IconInfo className="size-3" />
                </span>
            </Tooltip>
        </TableHead>
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
    return (
        <TableHead
            align={column.align}
            aria-sort={isSorted ? (sort.direction === 'DESC' ? 'descending' : 'ascending') : 'none'}
        >
            <Button
                size="sm"
                aria-selected={isSorted ? true : undefined}
                className={cn('gap-1.5', isSorted ? 'text-foreground' : 'hover:bg-fill-hover/50')}
                tooltip={column.tooltip}
                disabled={loading}
                onClick={() => onSort(column.key, nextDirection)}
            >
                {column.label}
                {!isSorted ? (
                    <IconSort className="size-3 opacity-50" />
                ) : sort.direction === 'DESC' ? (
                    <IconArrowDown className="size-3" />
                ) : (
                    <IconArrowUp className="size-3" />
                )}
            </Button>
        </TableHead>
    )
}

function ToolRowsSkeleton(): JSX.Element {
    return (
        <TableBody>
            {SKELETON_ROW_WIDTHS.map((width, i) => (
                <TableRow key={i}>
                    <TableCell expand>
                        <div className="flex flex-col gap-1.5 py-1">
                            <SkeletonLine style={{ width }} />
                            <SkeletonLine className="w-2/3" />
                        </div>
                    </TableCell>
                    <TableCell align="right">
                        <SkeletonLine className="ml-auto w-40" />
                    </TableCell>
                    {SORTABLE_COLUMNS.map((column) => (
                        <TableCell key={column.key} align={column.align}>
                            <SkeletonLine className={column.align === 'right' ? 'ml-auto w-10' : 'w-16'} />
                        </TableCell>
                    ))}
                </TableRow>
            ))}
        </TableBody>
    )
}

function ToolRowsError(): JSX.Element {
    const { loadToolRowsPage } = useActions(mcpAnalyticsToolQualityLogic)
    return (
        <TableEmpty className="py-6">
            <div className="flex flex-col items-center gap-2 text-center text-secondary">
                <span>Couldn't load your tools. Try again, or pick a shorter date range.</span>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => loadToolRowsPage()}
                    data-attr="mcp-tool-quality-rows-retry"
                >
                    Try again
                </Button>
            </div>
        </TableEmpty>
    )
}

function ToolRows(): JSX.Element {
    const { toolRows, toolRowsTotalSessions, toolRowsPreviousTotalSessions, selectedTool, dailyChartData, interval } =
        useValues(mcpAnalyticsToolQualityLogic)
    const { openToolDrawer } = useActions(mcpAnalyticsToolQualityLogic)
    const { facets } = useValues(mcpFacetsLogic)
    // The same threshold as the "Slow" filter, so amber means the same thing everywhere.
    const slowThresholdMs = facets?.p95 ? Math.round(facets.p95) : null

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
                    onClick={() => openToolDrawer(row.tool)}
                    data-attr="mcp-tool-quality-row"
                >
                    <TableCell expand>
                        <div className="flex min-w-0 flex-col gap-0.5 py-1">
                            <button
                                type="button"
                                className={TOOL_BUTTON_CLASS}
                                aria-pressed={row.tool === selectedTool}
                            >
                                {row.tool}
                            </button>
                            {row.description ? (
                                <span className="line-clamp-1 text-xs text-primary">{row.description}</span>
                            ) : null}
                            <span className="flex flex-wrap items-center gap-x-1.5 text-xs italic text-secondary">
                                {row.category ? (
                                    <>
                                        <span>{row.category}</span>
                                        <span aria-hidden>·</span>
                                    </>
                                ) : null}
                                <span>First called</span>
                                <TZLabel time={row.first_seen} />
                            </span>
                        </div>
                    </TableCell>
                    <TableCell align="right">
                        <ToolVolumeCell
                            tool={row.tool}
                            buckets={row.buckets ?? []}
                            labels={dailyChartData.labels}
                            interval={interval}
                            slowThresholdMs={slowThresholdMs}
                            lastSeen={row.last_seen}
                        />
                    </TableCell>
                    <TableCell align="right" className="tabular-nums">
                        {formatNumber(row.total_calls)}
                    </TableCell>
                    <TableCell align="right">
                        <TrendCell totalCalls={row.total_calls} previousCalls={row.previous_calls} />
                    </TableCell>
                    <TableCell align="right">
                        <span className="inline-flex items-center whitespace-nowrap">
                            <ErrorRateBadge pct={row.error_rate_pct} />
                            <QualityChangeMarker change={errorRateChange(row)} />
                        </span>
                    </TableCell>
                    <TableCell align="right">
                        <span className="inline-flex items-center whitespace-nowrap">
                            {slowThresholdMs !== null && row.p95_duration_ms > slowThresholdMs ? (
                                <Tooltip
                                    title={`Slower than the p95 of all calls (${formatMs(slowThresholdMs)}), the same threshold as the Slow filter. Volume bars turn amber in intervals above it.`}
                                >
                                    <span tabIndex={0}>
                                        <Badge variant="warning">{formatMs(row.p95_duration_ms)}</Badge>
                                    </span>
                                </Tooltip>
                            ) : (
                                <span className="tabular-nums">{formatMs(row.p95_duration_ms)}</span>
                            )}
                            <QualityChangeMarker change={p95Change(row)} />
                        </span>
                    </TableCell>
                    <TableCell align="right" className="tabular-nums">
                        {formatNumber(row.users)}
                    </TableCell>
                    <TableCell align="right">
                        <SessionsCell
                            sessions={row.sessions}
                            totalSessions={toolRowsTotalSessions}
                            previousSessions={row.previous_sessions}
                            previousTotalSessions={toolRowsPreviousTotalSessions}
                        />
                    </TableCell>
                </TableRow>
            ))}
        </TableBody>
    )
}

export function ToolQualityTable(): JSX.Element {
    const {
        toolQualitySort,
        toolQualityPageIndex,
        loadedToolQualityPageIndex,
        toolRows,
        toolRowsPage,
        toolRowsPageLoading,
        toolRowsLoadFailed,
        toolRowsTotalCount,
    } = useValues(mcpAnalyticsToolQualityLogic)
    const { setToolQualitySort, setToolQualityPageIndex } = useActions(mcpAnalyticsToolQualityLogic)
    const pageCount = Math.max(Math.ceil(toolRowsTotalCount / TOOL_QUALITY_PAGE_SIZE), 1)
    const pageRange = getPaginationRange(pageCount, toolQualityPageIndex)
    const firstRow = toolRowsTotalCount === 0 ? 0 : loadedToolQualityPageIndex * TOOL_QUALITY_PAGE_SIZE + 1
    const lastRow = Math.min(firstRow + toolRows.length - 1, toolRowsTotalCount)
    const showSkeleton = toolRowsPageLoading && toolRowsPage === null

    return (
        // pt-0: no card header.
        <Card size="sm" className="gap-0 overflow-hidden pt-0">
            <div className="relative">
                <Table fullWidth stickyHeader className="max-h-[44rem]" aria-busy={toolRowsPageLoading}>
                    <TableHeader>
                        <TableRow>
                            <TableHead expand>Tool</TableHead>
                            <VolumeHead />
                            {SORTABLE_COLUMNS.map((column) => (
                                <SortableHead
                                    key={column.key}
                                    column={column}
                                    sort={toolQualitySort}
                                    loading={toolRowsPageLoading}
                                    onSort={setToolQualitySort}
                                />
                            ))}
                        </TableRow>
                    </TableHeader>
                    {showSkeleton ? <ToolRowsSkeleton /> : toolRowsLoadFailed ? <ToolRowsError /> : <ToolRows />}
                </Table>
                {toolRowsPageLoading && !showSkeleton ? (
                    <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60">
                        <Spinner className="size-5" />
                    </div>
                ) : null}
            </div>
            {toolRowsTotalCount > 0 && (
                <CardFooter className="flex flex-row flex-wrap items-center justify-between gap-2 border-t border-border">
                    <Text size="xs" variant="muted" render={<span />} className="tabular-nums">
                        {firstRow}-{lastRow} of {pluralize(toolRowsTotalCount, 'tool')}
                    </Text>
                    {pageCount > 1 ? (
                        <Pagination className="w-auto">
                            <PaginationContent>
                                <PaginationItem>
                                    <PaginationPrevious
                                        disabled={toolRowsPageLoading || toolQualityPageIndex === 0}
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
                                                disabled={toolRowsPageLoading}
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
                                        disabled={toolRowsPageLoading || toolQualityPageIndex === pageCount - 1}
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
