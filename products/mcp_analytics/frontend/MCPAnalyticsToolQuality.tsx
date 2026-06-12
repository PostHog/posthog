import { useActions, useValues } from 'kea'

import { DataTable } from '@posthog/query-frontend/nodes/DataTable/DataTable'
import { Query } from '@posthog/query-frontend/Query/Query'
import { isHogQLQuery } from '@posthog/query-frontend/utils'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration } from 'lib/utils'
import { urls } from 'scenes/urls'

import { mcpAnalyticsToolQualityLogic } from './mcpAnalyticsToolQualityLogic'

const COLLECTION_ID = 'mcp-analytics-tool-quality'

function renderSortableTitle(
    column: string,
    title: string,
    currentSort: { column: string; direction: 'ASC' | 'DESC' },
    setSort: (column: string, direction: 'ASC' | 'DESC') => void
): JSX.Element {
    const isSorted = currentSort.column === column
    const handleClick = (): void => {
        const next = isSorted && currentSort.direction === 'DESC' ? 'ASC' : 'DESC'
        setSort(column, next)
    }
    return (
        <span
            onClick={handleClick}
            style={{ cursor: 'pointer', userSelect: 'none' }}
            className="flex items-center gap-1"
        >
            {title}
            {isSorted ? (currentSort.direction === 'DESC' ? ' ▼' : ' ▲') : ''}
        </span>
    )
}

function formatMs(value: unknown): string {
    if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) {
        return '—'
    }
    return humanFriendlyDuration(Number(value) / 1000, { secondsFixed: 2 })
}

function errorRateClass(rate: number): string {
    if (rate <= 0) {
        return 'text-success'
    }
    if (rate < 5) {
        return 'text-warning'
    }
    return 'text-danger'
}

function CategoryScopeBar(): JSX.Element {
    const { availableCategories, availableCategoriesLoading, selectedCategories, scopeShare } =
        useValues(mcpAnalyticsToolQualityLogic)
    const { setSelectedCategories } = useActions(mcpAnalyticsToolQualityLogic)

    const hasScope = selectedCategories.length > 0
    const sharePct = scopeShare.pct === null ? null : Math.round(scopeShare.pct * 10) / 10

    return (
        <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-[280px] flex-1 max-w-[480px]">
                <LemonInputSelect
                    mode="multiple"
                    value={selectedCategories}
                    onChange={setSelectedCategories}
                    options={availableCategories.map((category) => ({ key: category, label: category }))}
                    loading={availableCategoriesLoading}
                    placeholder="All categories"
                    data-attr="mcp-tool-quality-category-scope"
                />
            </div>
            {hasScope && sharePct !== null ? (
                <Tooltip
                    title={`${scopeShare.inScope.toLocaleString()} of ${scopeShare.total.toLocaleString()} MCP tool calls in the last 7 days were in the selected categories`}
                >
                    <div className="text-sm text-muted">
                        <span className="font-semibold text-default">{sharePct}%</span> of MCP usage (last 7d)
                    </div>
                </Tooltip>
            ) : null}
        </div>
    )
}

export function MCPAnalyticsToolQuality(): JSX.Element {
    const { toolQualityQuery, toolQualitySort, topToolsQuery, errorTrendQuery, durationTrendQuery } =
        useValues(mcpAnalyticsToolQualityLogic)
    const { setToolQualitySort, setDateFilter } = useActions(mcpAnalyticsToolQualityLogic)

    return (
        <div className="flex flex-col gap-4">
            <CategoryScopeBar />
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="bg-bg-light border rounded p-2 min-h-[260px] flex flex-col">
                    <div className="text-muted text-xs font-medium uppercase mb-2 px-2 pt-1">Top tools by calls</div>
                    <div className="flex-1">
                        <Query query={topToolsQuery} readOnly />
                    </div>
                </div>
                <div className="bg-bg-light border rounded p-2 min-h-[260px] flex flex-col">
                    <div className="text-muted text-xs font-medium uppercase mb-2 px-2 pt-1">Errors over time</div>
                    <div className="flex-1">
                        <Query query={errorTrendQuery} readOnly />
                    </div>
                </div>
                <div className="bg-bg-light border rounded p-2 min-h-[260px] flex flex-col">
                    <div className="text-muted text-xs font-medium uppercase mb-2 px-2 pt-1">Duration over time</div>
                    <div className="flex-1">
                        <Query query={durationTrendQuery} readOnly />
                    </div>
                </div>
            </div>
            <DataTable
                query={toolQualityQuery}
                setQuery={(query) => {
                    if (!isHogQLQuery(query.source)) {
                        return
                    }
                    const filters = query.source.filters ?? {}
                    const dateRange = filters.dateRange ?? {}
                    setDateFilter(dateRange.date_from ?? null, dateRange.date_to ?? null)
                }}
                context={{
                    columns: {
                        tool: {
                            title: 'Tool',
                            render: function RenderTool({ value }) {
                                if (!value || value === 'null') {
                                    return <span className="text-muted">Unknown tool</span>
                                }
                                const toolName = String(value)
                                return (
                                    <Link
                                        to={urls.mcpAnalyticsTool(toolName)}
                                        className="font-mono text-sm"
                                        data-attr="mcp-tool-quality-tool-link"
                                    >
                                        {toolName}
                                    </Link>
                                )
                            },
                        },
                        total_calls: {
                            renderTitle: () => (
                                <Tooltip title="Total number of times this tool was called">
                                    {renderSortableTitle(
                                        'total_calls',
                                        'Total calls',
                                        toolQualitySort,
                                        setToolQualitySort
                                    )}
                                </Tooltip>
                            ),
                        },
                        error_rate_pct: {
                            renderTitle: () => (
                                <Tooltip title="Percentage of calls that returned $mcp_is_error = true">
                                    {renderSortableTitle(
                                        'error_rate_pct',
                                        'Error rate',
                                        toolQualitySort,
                                        setToolQualitySort
                                    )}
                                </Tooltip>
                            ),
                            render: function RenderErrorRate({ value }) {
                                const numeric = Number(value)
                                if (Number.isNaN(numeric)) {
                                    return <span className="text-muted">—</span>
                                }
                                return <span className={errorRateClass(numeric)}>{numeric}%</span>
                            },
                        },
                        p95_duration_ms: {
                            renderTitle: () => (
                                <Tooltip title="95th-percentile $mcp_duration_ms">
                                    {renderSortableTitle(
                                        'p95_duration_ms',
                                        'p95 duration',
                                        toolQualitySort,
                                        setToolQualitySort
                                    )}
                                </Tooltip>
                            ),
                            render: ({ value }) => <span>{formatMs(value)}</span>,
                        },
                        p50_duration_ms: {
                            renderTitle: () => (
                                <Tooltip title="Median $mcp_duration_ms">
                                    {renderSortableTitle(
                                        'p50_duration_ms',
                                        'p50 duration',
                                        toolQualitySort,
                                        setToolQualitySort
                                    )}
                                </Tooltip>
                            ),
                            render: ({ value }) => <span>{formatMs(value)}</span>,
                        },
                        users: {
                            renderTitle: () => (
                                <Tooltip title="Unique users who invoked this tool">
                                    {renderSortableTitle('users', 'Users', toolQualitySort, setToolQualitySort)}
                                </Tooltip>
                            ),
                        },
                        sessions: {
                            renderTitle: () => (
                                <Tooltip title="Unique sessions where this tool was called">
                                    {renderSortableTitle('sessions', 'Sessions', toolQualitySort, setToolQualitySort)}
                                </Tooltip>
                            ),
                        },
                        last_seen: {
                            renderTitle: () =>
                                renderSortableTitle('last_seen', 'Last seen', toolQualitySort, setToolQualitySort),
                        },
                    },
                }}
                uniqueKey={COLLECTION_ID}
            />
        </div>
    )
}
