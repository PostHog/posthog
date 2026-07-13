import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonDivider, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import {
    type ChartTheme,
    type Series,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'
import {
    Card,
    CardDescription,
    CardHeader,
    CardTitle,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill-primitives'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneExport } from '~/scenes/sceneTypes'

import { formatBucketLabel, formatMs, formatMsAsSeconds } from './dashboard/formatters'
import { HarnessLogo, HarnessPill } from './dashboard/harness'
import { MetricTile } from './dashboard/MetricTile'
import { mcpAnalyticsFeaturePreviewGate } from './featurePreviewGate'
import {
    type DailyChartData,
    IntentCoverage,
    MCPAnalyticsToolDetailLogicProps,
    type ResultRows,
    ToolSummary,
    mcpAnalyticsToolDetailLogic,
} from './mcpAnalyticsToolDetailLogic'

export const scene: SceneExport<MCPAnalyticsToolDetailLogicProps> = {
    component: MCPAnalyticsToolDetail,
    logic: mcpAnalyticsToolDetailLogic,
    paramsToProps: ({ params: { toolName } }) => ({
        toolName: decodeURIComponent(toolName ?? ''),
    }),
}

// Renderer for the "person" column in the Top users table. The loader maps each row's
// person into a [distinct_id, _, person_properties] array. Wrap it back into the shape
// PersonDisplay expects.
function renderPersonCell(value: unknown): JSX.Element {
    if (!Array.isArray(value) || value.length === 0) {
        return <span className="text-muted">—</span>
    }
    const [distinctId, , propertiesRaw] = value as [string, unknown, unknown]
    let properties: Record<string, unknown> | undefined
    if (propertiesRaw && typeof propertiesRaw === 'object') {
        properties = propertiesRaw as Record<string, unknown>
    } else if (typeof propertiesRaw === 'string') {
        try {
            properties = JSON.parse(propertiesRaw)
        } catch {
            properties = undefined
        }
    }
    return (
        <PersonDisplay person={{ distinct_id: distinctId, properties: properties ?? {} }} withIcon noPopover={false} />
    )
}

// Harness logos for a row. Labels are resolved (deduped + sorted) server-side; the column
// just maps each label to its logo and stays on one line.
function HarnessLogos({ labels }: { labels: string[] }): JSX.Element {
    if (labels.length === 0) {
        return <span className="text-muted">—</span>
    }
    return (
        <div className="flex items-center gap-1">
            {labels.map((category) => (
                <HarnessLogo key={category} category={category} />
            ))}
        </div>
    )
}

interface ResultColumn {
    header: string
    align?: 'left' | 'right'
    expand?: boolean
    render: (row: unknown[]) => React.ReactNode
}

const neighborColumns: ResultColumn[] = [
    { header: 'Tool', expand: true, render: (r) => <span className="font-mono">{String(r[0] ?? '')}</span> },
    { header: 'In same conversation', align: 'right', render: (r) => humanFriendlyNumber(Number(r[1] ?? 0)) },
]

// Card-wrapped quill table matching the dashboard table cards.
function ResultTable({
    title,
    description,
    action,
    rows,
    loading,
    columns,
    emptyMessage = 'No data for the last 7 days.',
}: {
    title?: React.ReactNode
    description?: React.ReactNode
    action?: React.ReactNode
    rows: ResultRows
    loading: boolean
    columns: ResultColumn[]
    emptyMessage?: string
}): JSX.Element {
    return (
        <Card size="sm" className="gap-0">
            {title != null && (
                <CardHeader
                    className={`border-b border-border pb-3${
                        action != null ? ' !flex flex-row items-center justify-between gap-2' : ''
                    }`}
                >
                    <CardTitle>{title}</CardTitle>
                    {description != null && <CardDescription>{description}</CardDescription>}
                    {action}
                </CardHeader>
            )}
            <Table fullWidth>
                <TableHeader>
                    <TableRow>
                        {columns.map((col, i) => (
                            <TableHead key={i} align={col.align} expand={col.expand}>
                                {col.header}
                            </TableHead>
                        ))}
                    </TableRow>
                </TableHeader>
                {loading && rows.length === 0 ? (
                    <TableBody>
                        <TableRow>
                            <TableCell colSpan={columns.length}>
                                <div className="space-y-2 py-1">
                                    {Array.from({ length: 4 }).map((_, i) => (
                                        <Skeleton key={i} className="h-3.5 w-full" />
                                    ))}
                                </div>
                            </TableCell>
                        </TableRow>
                    </TableBody>
                ) : rows.length === 0 ? (
                    <TableEmpty className="py-6 text-secondary">{emptyMessage}</TableEmpty>
                ) : (
                    <TableBody>
                        {rows.map((row, i) => (
                            <TableRow key={i}>
                                {columns.map((col, ci) => (
                                    <TableCell key={ci} align={col.align} expand={col.expand}>
                                        {col.render(row)}
                                    </TableCell>
                                ))}
                            </TableRow>
                        ))}
                    </TableBody>
                )}
            </Table>
        </Card>
    )
}

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <h2 className="text-base font-semibold mb-0">{title}</h2>
            {subtitle ? <span className="text-xs text-secondary">{subtitle}</span> : null}
        </div>
    )
}

// Tile sparkline window — the trailing slice of the 30-day daily series.
const SPARKLINE_DAYS = 7

// Trailing window of a daily series, coalescing latency gaps (NaN) to 0 for the sparkline.
function spark(values: number[]): number[] {
    return values.slice(-SPARKLINE_DAYS).map((v) => (Number.isFinite(v) ? v : 0))
}

function StatTiles({
    summary,
    loading,
    daily,
    theme,
}: {
    summary: ToolSummary | null
    loading: boolean
    daily: DailyChartData
    theme: ChartTheme
}): JSX.Element {
    const calls = summary?.calls ?? 0
    const errors = summary?.errors ?? 0
    const errorRate = calls ? (errors / calls) * 100 : 0
    const errorRateDaily = daily.calls.map((c, i) => (c ? (daily.errors[i] / c) * 100 : 0))
    const sparkLabels = daily.labels.slice(-SPARKLINE_DAYS).map(formatBucketLabel)

    const tiles: {
        label: string
        value: number
        formatValue: (n: number) => string
        data: number[]
        color: string
        goodDirection: 'up' | 'down'
    }[] = [
        {
            label: 'Calls',
            value: calls,
            formatValue: humanFriendlyNumber,
            data: spark(daily.calls),
            color: theme.colors[0],
            goodDirection: 'up',
        },
        {
            label: 'Error rate',
            value: errorRate,
            formatValue: (n) => `${n.toFixed(1)}%`,
            data: spark(errorRateDaily),
            color: theme.colors[4],
            goodDirection: 'down',
        },
        {
            label: 'p50 latency',
            value: summary?.p50_ms ?? 0,
            formatValue: formatMs,
            data: spark(daily.p50),
            color: theme.colors[0],
            goodDirection: 'down',
        },
        {
            label: 'p95 latency',
            value: summary?.p95_ms ?? 0,
            formatValue: formatMs,
            data: spark(daily.p95),
            color: theme.colors[0],
            goodDirection: 'down',
        },
        {
            label: 'Users',
            value: summary?.users ?? 0,
            formatValue: humanFriendlyNumber,
            data: spark(daily.users),
            color: theme.colors[0],
            goodDirection: 'up',
        },
        {
            label: 'Sessions',
            value: summary?.conversations ?? 0,
            formatValue: humanFriendlyNumber,
            data: spark(daily.sessions),
            color: theme.colors[6],
            goodDirection: 'up',
        },
    ]

    return (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6" data-quill>
            {tiles.map((tile) => (
                <MetricTile
                    key={tile.label}
                    {...tile}
                    loading={loading}
                    labels={sparkLabels}
                    theme={theme}
                    restingSubtitle="Last 7 days"
                    sparklineHeight={40}
                />
            ))}
        </div>
    )
}

function IntentCoverageTag({
    coverage,
    loading,
}: {
    coverage: IntentCoverage | null
    loading: boolean
}): JSX.Element | null {
    if (loading) {
        return <LemonSkeleton className="h-4 w-32" />
    }
    if (!coverage || !coverage.total) {
        return null
    }
    const pct = Math.round((coverage.with_intent / coverage.total) * 100)
    return (
        <Tooltip title="Share of calls where $mcp_intent was captured. Inferred intents are server fallbacks; context_parameter intents come from the client.">
            <span className="text-[11px] text-secondary">
                {humanFriendlyNumber(coverage.with_intent)} of {humanFriendlyNumber(coverage.total)} calls captured
                intent ({pct}%)
            </span>
        </Tooltip>
    )
}

function DescriptionBlock({
    descriptions,
    loading,
}: {
    descriptions: { description: string; last_seen: string }[]
    loading: boolean
}): JSX.Element | null {
    if (loading) {
        return <LemonSkeleton className="h-8 w-2/3 mt-2" />
    }
    if (!descriptions.length) {
        return null
    }
    const [latest, ...older] = descriptions
    return (
        <div className="flex flex-col gap-1 max-w-3xl">
            <span className="text-[11px] uppercase tracking-wider text-secondary">Description</span>
            <LemonMarkdown className="text-sm leading-snug line-clamp-3" lowKeyHeadings>
                {latest.description}
            </LemonMarkdown>
            {older.length > 0 ? (
                <Tooltip
                    title={
                        <div className="flex flex-col gap-2 max-w-md">
                            {older.map((d) => (
                                <div key={d.last_seen} className="text-xs">
                                    <div className="text-secondary mb-0.5">
                                        last seen <TZLabel time={d.last_seen} />
                                    </div>
                                    <LemonMarkdown lowKeyHeadings>{d.description}</LemonMarkdown>
                                </div>
                            ))}
                        </div>
                    }
                >
                    <span className="text-[11px] text-secondary underline decoration-dotted cursor-help w-fit">
                        + {older.length} previous version{older.length === 1 ? '' : 's'}
                    </span>
                </Tooltip>
            ) : null}
        </div>
    )
}

function trendChartConfig(timezone: string, yAxis?: TimeSeriesLineChartConfig['yAxis']): TimeSeriesLineChartConfig {
    return {
        curve: 'monotone',
        showAxisLines: true,
        showTickMarks: true,
        showCrosshair: true,
        showGrid: true,
        yAxis,
        xAxis: { interval: 'day', timezone },
        tooltip: { placement: 'cursor' },
    }
}

type TrendSeriesKey = 'calls' | 'errors' | 'p50' | 'p95'
const SERIES_META: Record<TrendSeriesKey, { label: string; colorIndex: number }> = {
    calls: { label: 'Calls', colorIndex: 0 },
    errors: { label: 'Errors', colorIndex: 4 },
    p50: { label: 'p50', colorIndex: 1 },
    p95: { label: 'p95', colorIndex: 0 },
}

function seriesFor(data: DailyChartData, theme: ChartTheme, keys: TrendSeriesKey[]): Series[] {
    return keys.map((key) => ({
        key,
        label: SERIES_META[key].label,
        color: theme.colors[SERIES_META[key].colorIndex],
        data: data[key],
    }))
}

function TrendChart({
    title,
    series,
    labels,
    config,
    theme,
    loading,
    dataAttr,
}: {
    title: string
    series: Series[]
    labels: string[]
    config: TimeSeriesLineChartConfig
    theme: ChartTheme
    loading: boolean
    dataAttr: string
}): JSX.Element {
    return (
        <div className="flex flex-col rounded border bg-bg-light p-2" style={{ height: 240 }} data-quill>
            <div className="mb-1 px-2 pt-1 text-xs font-medium uppercase text-secondary">{title}</div>
            <div className="flex min-h-0 flex-1 flex-col">
                {loading && labels.length === 0 ? (
                    <Skeleton className="flex-1" />
                ) : labels.length === 0 ? (
                    <div className="flex flex-1 items-center justify-center text-[12px] text-secondary">
                        No data for the last 7 days.
                    </div>
                ) : (
                    <TimeSeriesLineChart
                        series={series}
                        labels={labels}
                        config={config}
                        theme={theme}
                        dataAttr={dataAttr}
                    />
                )}
            </div>
        </div>
    )
}

export function MCPAnalyticsToolDetail({ toolName }: { toolName: string }): JSX.Element {
    return (
        <FeaturePreviewSceneGate config={mcpAnalyticsFeaturePreviewGate}>
            <MCPAnalyticsToolDetailContent toolName={toolName} />
        </FeaturePreviewSceneGate>
    )
}

function MCPAnalyticsToolDetailContent({ toolName }: { toolName: string }): JSX.Element {
    const {
        summary,
        summaryLoading,
        descriptions,
        descriptionsLoading,
        dailyChartData,
        dailyStatsLoading,
        failureRows,
        failureRowsLoading,
        sampleIntentRows,
        sampleIntentRowsLoading,
        intentCoverage,
        intentCoverageLoading,
        neighborsBeforeRows,
        neighborsBeforeRowsLoading,
        neighborsAfterRows,
        neighborsAfterRowsLoading,
        byHarnessRows,
        byHarnessRowsLoading,
        topUserRows,
        topUserRowsLoading,
    } = useValues(mcpAnalyticsToolDetailLogic({ toolName }))
    const { timezone } = useValues(teamLogic)

    const theme = useChartTheme()
    const callsSeries = useMemo<Series[]>(
        () => seriesFor(dailyChartData, theme, ['calls', 'errors']),
        [dailyChartData, theme]
    )
    const latencySeries = useMemo<Series[]>(
        () => seriesFor(dailyChartData, theme, ['p50', 'p95']),
        [dailyChartData, theme]
    )
    const countsConfig = useChartConfig(() => trendChartConfig(timezone), [timezone])
    const latencyConfig = useChartConfig(
        () => trendChartConfig(timezone, { tickFormatter: formatMsAsSeconds }),
        [timezone]
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name={toolName}
                description={null}
                resourceType={{ type: 'llm_analytics' }}
                forceBackTo={{
                    name: 'Tool quality',
                    path: urls.mcpAnalyticsToolQuality(),
                    key: 'mcp-analytics-tool-quality',
                }}
            />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <DescriptionBlock descriptions={descriptions} loading={descriptionsLoading} />
                <StatTiles summary={summary} loading={summaryLoading} daily={dailyChartData} theme={theme} />
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader title="Reliability" subtitle="Last 30 days" />
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <TrendChart
                        title="Calls and errors"
                        series={callsSeries}
                        labels={dailyChartData.labels}
                        config={countsConfig}
                        theme={theme}
                        loading={dailyStatsLoading}
                        dataAttr="mcp-tool-detail-calls-chart"
                    />
                    <TrendChart
                        title="Duration (p50 / p95)"
                        series={latencySeries}
                        labels={dailyChartData.labels}
                        config={latencyConfig}
                        theme={theme}
                        loading={dailyStatsLoading}
                        dataAttr="mcp-tool-detail-latency-chart"
                    />
                </div>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader title="Usage flow" />
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <ResultTable
                        title="Sample intents"
                        action={<IntentCoverageTag coverage={intentCoverage} loading={intentCoverageLoading} />}
                        rows={sampleIntentRows}
                        loading={sampleIntentRowsLoading}
                        emptyMessage="No intents captured in the last 7 days."
                        columns={[
                            { header: 'When', render: (r) => <TZLabel time={String(r[0])} /> },
                            { header: 'Intent', expand: true, render: (r) => <span>{String(r[1] ?? '')}</span> },
                            { header: 'Intent source', render: (r) => <span>{String(r[2] ?? '')}</span> },
                            { header: 'Harness', render: (r) => <span>{String(r[3] ?? '')}</span> },
                        ]}
                    />
                    <div className="flex flex-col gap-4">
                        <ResultTable
                            title={
                                <span className="flex items-center gap-1">
                                    <IconArrowLeft className="text-base" />
                                    Often called before (same conversation)
                                </span>
                            }
                            rows={neighborsBeforeRows}
                            loading={neighborsBeforeRowsLoading}
                            emptyMessage="No tools commonly precede this one."
                            columns={neighborColumns}
                        />
                        <ResultTable
                            title={
                                <span className="flex items-center gap-1">
                                    <IconArrowRight className="text-base" />
                                    Often called after (same conversation)
                                </span>
                            }
                            rows={neighborsAfterRows}
                            loading={neighborsAfterRowsLoading}
                            emptyMessage="No tools commonly follow this one."
                            columns={neighborColumns}
                        />
                    </div>
                </div>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader title="Who uses it" />
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <ResultTable
                        title="By harness"
                        rows={byHarnessRows}
                        loading={byHarnessRowsLoading}
                        columns={[
                            {
                                header: 'Harness',
                                expand: true,
                                render: (r) => {
                                    const label = String(r[0] ?? '')
                                    return label ? (
                                        <HarnessPill category={label} title={label} />
                                    ) : (
                                        <span className="text-muted">Unknown</span>
                                    )
                                },
                            },
                            {
                                header: 'Calls',
                                align: 'right',
                                render: (r) => humanFriendlyNumber(Number(r[1] ?? 0)),
                            },
                            {
                                header: 'Errors',
                                align: 'right',
                                render: (r) => humanFriendlyNumber(Number(r[2] ?? 0)),
                            },
                            { header: 'Error rate', align: 'right', render: (r) => `${Number(r[3] ?? 0)}%` },
                            {
                                header: 'Sessions',
                                align: 'right',
                                render: (r) => humanFriendlyNumber(Number(r[4] ?? 0)),
                            },
                        ]}
                    />
                    <ResultTable
                        title="Top users"
                        rows={topUserRows}
                        loading={topUserRowsLoading}
                        columns={[
                            { header: 'User', expand: true, render: (r) => renderPersonCell(r[0]) },
                            {
                                header: 'Calls',
                                align: 'right',
                                render: (r) => humanFriendlyNumber(Number(r[1] ?? 0)),
                            },
                            {
                                header: 'Errors',
                                align: 'right',
                                render: (r) => humanFriendlyNumber(Number(r[2] ?? 0)),
                            },
                            { header: 'Error rate', align: 'right', render: (r) => `${Number(r[3] ?? 0)}%` },
                            {
                                header: 'Harnesses',
                                render: (r) => <HarnessLogos labels={(r[4] as string[]) ?? []} />,
                            },
                            { header: 'Last seen', render: (r) => <TZLabel time={String(r[5])} /> },
                        ]}
                    />
                </div>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <ResultTable
                    title="Failures"
                    description="Top exception messages paired with this tool. Sourced from $exception events."
                    rows={failureRows}
                    loading={failureRowsLoading}
                    emptyMessage="No exceptions recorded for this tool in the last 7 days."
                    columns={[
                        {
                            header: 'Message',
                            expand: true,
                            render: (r) => <span className="font-mono text-xs">{String(r[0] ?? '')}</span>,
                        },
                        {
                            header: 'Occurrences',
                            align: 'right',
                            render: (r) => humanFriendlyNumber(Number(r[1] ?? 0)),
                        },
                        { header: 'Last seen', render: (r) => <TZLabel time={String(r[2])} /> },
                        {
                            header: 'Harnesses',
                            render: (r) => <HarnessLogos labels={(r[3] as string[]) ?? []} />,
                        },
                    ]}
                />
            </div>
        </SceneContent>
    )
}

export default MCPAnalyticsToolDetail
