import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDivider, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { type ChartTheme, type TimeInterval } from '@posthog/quill-charts'
import {
    Card,
    CardDescription,
    CardHeader,
    CardTitle,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill-primitives'

import { useChartTheme } from 'lib/charts/hooks'
import { BrandMark } from 'lib/components/BrandMark/BrandMark'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { formatPercentage } from 'lib/utils/numbers'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { labMark, modelLab } from './aiLabs'
import { ToolDetailIntentsSection } from './clustering/ToolDetailIntentsSection'
import { InstrumentationEmptyState } from './components/InstrumentationEmptyState'
import { formatMs, formatNumber } from './dashboard/formatters'
import { HarnessLogo } from './dashboard/harness'
import { UNIDENTIFIED_HARNESS_LABEL } from './dashboard/harnessRegistry'
import { MetricTile } from './dashboard/MetricTile'
import { SkeletonLine } from './dashboard/SkeletonLine'
import { INSTRUMENTATION_FIXES } from './instrumentationFixes'
import { isMostlyLabeled } from './leaderboardHome/leaderboardShares'
import {
    type DailyChartData,
    type ResultRows,
    ToolSummary,
    mcpAnalyticsToolDetailLogic,
} from './mcpAnalyticsToolDetailLogic'
import { ExampleSessionDrawer } from './tool-quality/ExampleSessionDrawer'
import { ToolExamples } from './tool-quality/ToolExamples'
import { ToolJourneySankey } from './tool-quality/ToolJourneySankey'

// Renderer for the "person" column in the Top people table. The loader maps each row's
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
                <HarnessLogo key={category} category={category} label={category} />
            ))}
        </div>
    )
}

export interface ResultColumn {
    header: string
    align?: 'left' | 'right'
    expand?: boolean
    // Applied to both the header and cell, e.g. `@max-2xl:hidden` to drop a lower-priority column
    // once the card narrows past a container breakpoint instead of letting the table overflow it.
    className?: string
    render: (row: unknown[]) => React.ReactNode
}

const SKELETON_ROW_WIDTHS = ['70%', '50%', '85%', '40%']

// Card-wrapped quill table matching the dashboard table cards.
export function ResultTable({
    title,
    description,
    action,
    rows,
    loading,
    columns,
    emptyMessage = 'No data for the selected date range.',
    onRowClick,
    pageSize,
    setupEmptyState,
}: {
    title?: React.ReactNode
    description?: React.ReactNode
    action?: React.ReactNode
    rows: ResultRows
    loading: boolean
    columns: ResultColumn[]
    emptyMessage?: string
    onRowClick?: (rowIndex: number) => void
    /** Rows shown before "Show more". */
    pageSize?: number
    /** Replaces the table when the server doesn't send this value. */
    setupEmptyState?: React.ReactNode
}): JSX.Element {
    const [shownCount, setShownCount] = useState(pageSize ?? Infinity)
    const shownRows = rows.slice(0, shownCount)
    const hiddenCount = rows.length - shownRows.length
    return (
        <Card size="sm" className="@container gap-0">
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
            {setupEmptyState ? (
                setupEmptyState
            ) : (
                <Table fullWidth>
                    <TableHeader>
                        <TableRow>
                            {columns.map((col, i) => (
                                <TableHead key={i} align={col.align} expand={col.expand} className={col.className}>
                                    {col.header}
                                </TableHead>
                            ))}
                        </TableRow>
                    </TableHeader>
                    {loading && rows.length === 0 ? (
                        <TableBody aria-busy>
                            {SKELETON_ROW_WIDTHS.map((width, i) => (
                                <TableRow key={i}>
                                    {columns.map((col, j) => (
                                        <TableCell
                                            key={j}
                                            align={col.align}
                                            expand={col.expand}
                                            className={col.className}
                                        >
                                            <SkeletonLine
                                                className={col.align === 'right' ? 'ml-auto w-10' : undefined}
                                                style={col.align === 'right' ? undefined : { width }}
                                            />
                                        </TableCell>
                                    ))}
                                </TableRow>
                            ))}
                        </TableBody>
                    ) : rows.length === 0 ? (
                        <TableEmpty className="py-6 text-secondary">{emptyMessage}</TableEmpty>
                    ) : (
                        <TableBody>
                            {shownRows.map((row, i) => (
                                <TableRow
                                    key={i}
                                    className={onRowClick ? 'cursor-pointer hover:bg-fill-highlight-50' : undefined}
                                    onClick={onRowClick ? () => onRowClick(i) : undefined}
                                    // A bare <tr> isn't keyboard-operable — mirror the tracing tables'
                                    // pattern so the drill-down opens on Enter/Space too.
                                    role={onRowClick ? 'button' : undefined}
                                    tabIndex={onRowClick ? 0 : undefined}
                                    onKeyDown={
                                        onRowClick
                                            ? (e: React.KeyboardEvent) => {
                                                  if (e.key === 'Enter' || e.key === ' ') {
                                                      e.preventDefault()
                                                      onRowClick(i)
                                                  }
                                              }
                                            : undefined
                                    }
                                >
                                    {columns.map((col, ci) => (
                                        <TableCell
                                            key={ci}
                                            align={col.align}
                                            expand={col.expand}
                                            className={col.className}
                                        >
                                            {col.render(row)}
                                        </TableCell>
                                    ))}
                                </TableRow>
                            ))}
                        </TableBody>
                    )}
                </Table>
            )}
            {!setupEmptyState && pageSize && rows.length > pageSize ? (
                <div className="flex justify-center border-t border-border py-1.5">
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={() => setShownCount(hiddenCount > 0 ? shownCount + pageSize : pageSize)}
                        data-attr="mcp-tool-top-show-more"
                    >
                        {hiddenCount > 0 ? `Show ${Math.min(pageSize, hiddenCount)} more` : 'Show less'}
                    </LemonButton>
                </div>
            ) : null}
        </Card>
    )
}

const mostlyMissing = (rows: ResultRows, labels: string[]): boolean =>
    isMostlyLabeled(
        rows.map((r) => ({ label: String(r[0] ?? ''), calls: Number(r[1] ?? 0) })),
        labels
    )

export function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <h2 className="text-base font-semibold mb-0">{title}</h2>
            {subtitle ? <span className="text-xs text-secondary">{subtitle}</span> : null}
        </div>
    )
}

// Coalesce latency gaps (NaN) to 0 so the sparkline draws a continuous line over the window.
function spark(values: number[]): number[] {
    return values.map((v) => (Number.isFinite(v) ? v : 0))
}

// formatPercentage keeps two significant digits, so a tiny share would read like "0.00004%".
const MIN_DISPLAYED_SHARE_PCT = 0.01

// undefined when there's nothing to divide by, so the caller can fall back to the date range subtitle.
function formatShare(part: number, total: number): string | undefined {
    if (total === 0) {
        return undefined
    }
    const pct = (part / total) * 100
    if (pct > 0 && pct < MIN_DISPLAYED_SHARE_PCT) {
        return `<${MIN_DISPLAYED_SHARE_PCT}%`
    }
    return formatPercentage(pct, { compact: true })
}

function formatCallShare(calls: number, totalCalls: number): string | undefined {
    const share = formatShare(calls, totalCalls)
    return share === undefined ? undefined : `${share} of all calls`
}

function formatSessionShare(sessions: number, totalSessions: number): string | undefined {
    const share = formatShare(sessions, totalSessions)
    return share === undefined ? undefined : `In ${share} of sessions`
}

function StatTiles({
    summary,
    loading,
    daily,
    theme,
    dateRangeLabel,
    interval,
    incompleteTail,
}: {
    summary: ToolSummary | null
    loading: boolean
    daily: DailyChartData
    theme: ChartTheme
    dateRangeLabel: string
    interval: TimeInterval
    // When true, the final bucket is the current in-progress interval — dash the sparkline from
    // there so a partial period doesn't read as a decline. Required rather than optional: an
    // omitted prop silently renders the partial bucket as settled data.
    incompleteTail: boolean
}): JSX.Element {
    const calls = summary?.calls ?? 0
    const errors = summary?.errors ?? 0
    const errorRate = calls ? (errors / calls) * 100 : 0
    const errorRateDaily = daily.calls.map((c, i) => (c ? (daily.errors[i] / c) * 100 : 0))

    const tiles: {
        label: string
        value: number
        formatValue: (n: number) => string
        data: number[]
        color: string
        goodDirection: 'up' | 'down'
        subtitle?: string
    }[] = [
        {
            label: 'Calls',
            value: calls,
            formatValue: formatNumber,
            data: spark(daily.calls),
            color: theme.colors[0],
            goodDirection: 'up',
            subtitle: formatCallShare(calls, summary?.total_calls ?? 0),
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
            label: 'People',
            value: summary?.users ?? 0,
            formatValue: formatNumber,
            data: spark(daily.users),
            color: theme.colors[0],
            goodDirection: 'up',
        },
        {
            label: 'Sessions',
            value: summary?.conversations ?? 0,
            formatValue: formatNumber,
            data: spark(daily.sessions),
            color: theme.colors[6],
            goodDirection: 'up',
            subtitle: formatSessionShare(summary?.conversations ?? 0, summary?.total_conversations ?? 0),
        },
    ]

    return (
        <div className="grid grid-cols-2 gap-3 @2xl:grid-cols-3 @5xl:grid-cols-6" data-quill>
            {tiles.map((tile) => (
                <MetricTile
                    key={tile.label}
                    {...tile}
                    loading={loading}
                    labels={daily.labels}
                    interval={interval}
                    theme={theme}
                    restingSubtitle={tile.subtitle ?? dateRangeLabel}
                    sparklineHeight={40}
                    sparklineDashedFromIndex={incompleteTail ? daily.labels.length - 1 : undefined}
                />
            ))}
        </div>
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

type TopTab = 'harnesses' | 'models' | 'users'

const TOP_TABS: { value: TopTab; label: string }[] = [
    { value: 'harnesses', label: 'Harnesses' },
    { value: 'models', label: 'Models' },
    { value: 'users', label: 'People' },
]

const TOP_PAGE_SIZE = 5

/** One tool's report, on its page and in drawers. */
export function MCPToolReport(): JSX.Element {
    const {
        toolName,
        summary,
        summaryLoading,
        descriptions,
        descriptionsLoading,
        dailyChartData,
        journey,
        journeyLoading,
        byHarnessRows,
        byHarnessRowsLoading,
        topModelRows,
        topModelRowsLoading,
        topUserRows,
        topUserRowsLoading,
        dateRangeLabel,
        interval,
        incompleteTail,
    } = useValues(mcpAnalyticsToolDetailLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const intentRoutingEnabled = !!featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_INTENT_ROUTING]

    const theme = useChartTheme()
    const [topTab, setTopTab] = useState<TopTab>('harnesses')

    return (
        <div className="@container flex flex-col gap-y-4">
            <div className="flex flex-col gap-3 px-4 pb-4">
                <DescriptionBlock descriptions={descriptions} loading={descriptionsLoading} />
                <StatTiles
                    summary={summary}
                    loading={summaryLoading}
                    daily={dailyChartData}
                    theme={theme}
                    dateRangeLabel={dateRangeLabel}
                    interval={interval}
                    incompleteTail={incompleteTail}
                />
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader title="Examples" />
                <ToolExamples key={toolName} />
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader title="Session journeys" />
                <ToolJourneySankey toolName={toolName} journey={journey} loading={journeyLoading} />
            </div>

            {intentRoutingEnabled && (
                <>
                    <LemonDivider />

                    <div className="flex flex-col gap-3 px-4 pb-4">
                        <SectionHeader title="Intents served" subtitle="From the latest intent cluster snapshot" />
                        <ToolDetailIntentsSection toolName={toolName} />
                    </div>
                </>
            )}

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader title="Top" />
                <ToggleGroup
                    className="self-start"
                    value={[topTab]}
                    onValueChange={(next) => next[0] && setTopTab(next[0] as TopTab)}
                    aria-label="Top breakdown"
                >
                    {TOP_TABS.map((tab) => (
                        <ToggleGroupItem
                            key={tab.value}
                            value={tab.value}
                            size="sm"
                            data-attr={`mcp-tool-top-${tab.value}`}
                        >
                            {tab.label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
                {topTab === 'harnesses' ? (
                    <ResultTable
                        rows={byHarnessRows}
                        loading={byHarnessRowsLoading}
                        pageSize={TOP_PAGE_SIZE}
                        key={topTab}
                        setupEmptyState={
                            mostlyMissing(byHarnessRows, ['', UNIDENTIFIED_HARNESS_LABEL]) ? (
                                <InstrumentationEmptyState
                                    fix={INSTRUMENTATION_FIXES.harness}
                                    dataAttr="mcp-tool-top-harnesses-setup"
                                />
                            ) : undefined
                        }
                        columns={[
                            {
                                header: 'Harness',
                                expand: true,
                                render: (r) => {
                                    const label = String(r[0] ?? '')
                                    return label ? (
                                        <span className="flex items-center gap-1.5">
                                            <HarnessLogo category={label} className="size-4 shrink-0" />
                                            <span className="truncate">{label}</span>
                                        </span>
                                    ) : (
                                        <span className="text-muted">Unknown</span>
                                    )
                                },
                            },
                            {
                                header: 'Calls',
                                align: 'right',
                                render: (r) => formatNumber(Number(r[1] ?? 0)),
                            },
                            {
                                header: 'Errors',
                                align: 'right',
                                className: '@max-2xl:hidden',
                                render: (r) => formatNumber(Number(r[2] ?? 0)),
                            },
                            { header: 'Error rate', align: 'right', render: (r) => `${Number(r[3] ?? 0)}%` },
                            {
                                header: 'Sessions',
                                align: 'right',
                                className: '@max-2xl:hidden',
                                render: (r) => formatNumber(Number(r[4] ?? 0)),
                            },
                            {
                                header: 'Session share',
                                align: 'right',
                                render: (r) => formatShare(Number(r[4] ?? 0), Number(r[5] ?? 0)) ?? '-',
                            },
                        ]}
                    />
                ) : topTab === 'models' ? (
                    <ResultTable
                        rows={topModelRows}
                        loading={topModelRowsLoading}
                        pageSize={TOP_PAGE_SIZE}
                        key={topTab}
                        setupEmptyState={
                            mostlyMissing(topModelRows, ['', 'Unknown']) ? (
                                <InstrumentationEmptyState
                                    fix={INSTRUMENTATION_FIXES.model}
                                    dataAttr="mcp-tool-top-models-setup"
                                />
                            ) : undefined
                        }
                        columns={[
                            {
                                header: 'Model',
                                expand: true,
                                render: (r) => {
                                    const model = String(r[0] ?? '')
                                    return model !== 'Unknown' ? (
                                        <span className="flex items-center gap-1.5">
                                            <BrandMark name={labMark(modelLab(model))} className="size-4 shrink-0" />
                                            <span className="truncate">{model}</span>
                                        </span>
                                    ) : (
                                        <span className="text-muted">Unknown</span>
                                    )
                                },
                            },
                            { header: 'Calls', align: 'right', render: (r) => formatNumber(Number(r[1] ?? 0)) },
                            {
                                header: 'Errors',
                                align: 'right',
                                className: '@max-2xl:hidden',
                                render: (r) => formatNumber(Number(r[2] ?? 0)),
                            },
                            {
                                header: 'Error rate',
                                align: 'right',
                                render: (r) =>
                                    formatPercentage(Number(r[1]) > 0 ? (Number(r[2] ?? 0) / Number(r[1])) * 100 : 0, {
                                        compact: true,
                                    }),
                            },
                            { header: 'People', align: 'right', render: (r) => formatNumber(Number(r[3] ?? 0)) },
                        ]}
                    />
                ) : (
                    <ResultTable
                        rows={topUserRows}
                        loading={topUserRowsLoading}
                        pageSize={TOP_PAGE_SIZE}
                        key={topTab}
                        columns={[
                            { header: 'User', expand: true, render: (r) => renderPersonCell(r[0]) },
                            {
                                header: 'Calls',
                                align: 'right',
                                render: (r) => formatNumber(Number(r[1] ?? 0)),
                            },
                            {
                                header: 'Errors',
                                align: 'right',
                                className: '@max-2xl:hidden',
                                render: (r) => formatNumber(Number(r[2] ?? 0)),
                            },
                            { header: 'Error rate', align: 'right', render: (r) => `${Number(r[3] ?? 0)}%` },
                            {
                                header: 'Harnesses',
                                render: (r) => <HarnessLogos labels={(r[4] as string[]) ?? []} />,
                            },
                            {
                                header: 'Last seen',
                                className: '@max-2xl:hidden',
                                render: (r) => <TZLabel time={String(r[5])} />,
                            },
                        ]}
                    />
                )}
            </div>

            <ExampleSessionDrawer />
        </div>
    )
}
