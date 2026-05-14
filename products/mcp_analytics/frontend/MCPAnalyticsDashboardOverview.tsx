import { useValues } from 'kea'

import { IconBolt } from '@posthog/icons'
import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { humanFriendlyDuration, humanFriendlyNumber } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { JourneySankey } from './JourneySankey'
import claudeLogo from './harness-logos/claude.svg'
import cursorLogo from './harness-logos/cursor.svg'
import openaiLogo from './harness-logos/openai.svg'
import vscodeLogo from './harness-logos/vscode.svg'
import {
    DashboardJourney,
    HarnessRow,
    KPIMetric,
    NotableSession,
    ToolRow,
    mcpDashboardOverviewLogic,
} from './mcpDashboardOverviewLogic'

const HARNESS_LOGOS: Record<string, string> = {
    'Claude Code': claudeLogo,
    'Claude.ai': claudeLogo,
    'OpenAI Codex': openaiLogo,
    Cursor: cursorLogo,
    'VS Code': vscodeLogo,
}

export function HarnessPill({ category, title }: { category: string; title?: string }): JSX.Element {
    const logo = HARNESS_LOGOS[category]
    return (
        <span
            className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-primary bg-surface-primary px-2 py-0.5 text-xs"
            title={title}
        >
            {logo ? (
                <img src={logo} alt="" className="h-3.5 w-3.5 shrink-0 object-contain" />
            ) : (
                <span className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-secondary" aria-hidden />
            )}
            <span className="truncate">{category}</span>
        </span>
    )
}

type TileColor = 'blue' | 'red' | 'green'
type DeltaKind = 'pct' | 'pp' | 'ms' | 'count'

interface TileSpec {
    label: string
    metric: KPIMetric
    href: string
    format: (n: number) => string
    color: TileColor
    loading: boolean
    deltaKind: DeltaKind
}

const COLOR_STROKE: Record<TileColor, string> = {
    blue: '#185FA5',
    red: '#A32D2D',
    green: '#0F6E56',
}

function formatNumber(n: number): string {
    if (!isFinite(n)) {
        return '—'
    }
    return humanFriendlyNumber(Math.round(n))
}

function formatPercent(n: number): string {
    if (!isFinite(n)) {
        return '—'
    }
    return `${n.toFixed(n >= 10 ? 0 : 1)}%`
}

function formatMs(n: number): string {
    if (!isFinite(n) || n === 0) {
        return '—'
    }
    if (n < 1000) {
        return `${Math.round(n)}ms`
    }
    return humanFriendlyDuration(n / 1000, { secondsPrecision: 1 })
}

function Sparkline({ values, stroke }: { values: number[]; stroke: string }): JSX.Element {
    const width = 60
    const height = 18
    if (values.length === 0) {
        return <svg width={width} height={height} aria-hidden />
    }
    const max = Math.max(...values, 1)
    const min = Math.min(...values, 0)
    const range = max - min || 1
    const stepX = values.length > 1 ? width / (values.length - 1) : width
    const points = values
        .map((v, i) => {
            const x = i * stepX
            const y = height - ((v - min) / range) * height
            return `${x.toFixed(1)},${y.toFixed(1)}`
        })
        .join(' ')
    return (
        <svg width={width} height={height} aria-hidden>
            <polyline fill="none" stroke={stroke} strokeWidth="1.2" points={points} />
        </svg>
    )
}

function formatDelta(metric: KPIMetric, kind: DeltaKind): { text: string; signed: number } | null {
    const absDelta = metric.value - metric.previousValue
    switch (kind) {
        case 'pct':
            if (metric.deltaPct === null) {
                return null
            }
            return { text: `${formatSigned(metric.deltaPct, 0)}%`, signed: metric.deltaPct }
        case 'pp': {
            // Absolute percent-point delta — for metrics that are themselves percentages.
            const rounded = Math.round(absDelta * 10) / 10
            return { text: `${formatSigned(rounded, 1)}pp`, signed: rounded }
        }
        case 'ms': {
            const rounded = Math.round(absDelta)
            return { text: `${formatSigned(rounded, 0)}ms`, signed: rounded }
        }
        case 'count':
        default: {
            const rounded = Math.round(absDelta)
            return { text: formatSigned(rounded, 0), signed: rounded }
        }
    }
}

function formatSigned(n: number, decimals: number): string {
    if (n === 0) {
        return '0'
    }
    const sign = n > 0 ? '+' : '−'
    return `${sign}${Math.abs(n).toFixed(decimals)}`
}

function DeltaPill({ metric, kind }: { metric: KPIMetric; kind: DeltaKind }): JSX.Element {
    const delta = formatDelta(metric, kind)
    if (!delta) {
        return <span className="text-[11px] font-medium text-secondary">—</span>
    }
    if (delta.signed === 0) {
        return <span className="text-[11px] font-medium text-secondary">{delta.text}</span>
    }
    const isUp = delta.signed > 0
    const isGood = isUp ? metric.goodDirection === 'up' : metric.goodDirection === 'down'
    const colorClass = isGood ? 'text-success' : 'text-danger'
    return <span className={`text-[11px] font-medium ${colorClass}`}>{delta.text}</span>
}

function KPITile({ tile }: { tile: TileSpec }): JSX.Element {
    return (
        <Link
            to={tile.href}
            className="flex flex-col gap-1 rounded-md bg-surface-secondary px-3.5 py-3 transition-colors hover:bg-surface-tertiary"
        >
            <div className="text-[11px] text-secondary">{tile.label}</div>
            {tile.loading ? (
                <LemonSkeleton className="h-5 w-16" />
            ) : (
                <div className="text-xl font-medium leading-tight">{tile.format(tile.metric.value)}</div>
            )}
            <div className="mt-1 flex items-center justify-between">
                <Sparkline values={tile.metric.sparkline} stroke={COLOR_STROKE[tile.color]} />
                <DeltaPill metric={tile.metric} kind={tile.deltaKind} />
            </div>
        </Link>
    )
}

export function MCPAnalyticsDashboardOverview(): JSX.Element {
    const {
        kpis,
        kpisLoading,
        intentClusterCount,
        topToolRows,
        toolRowsLoading,
        toolRowsTotal,
        notableSessions,
        sessionRowsLoading,
        dashboardJourney,
        harnessRows,
        harnessRawRowsLoading,
    } = useValues(mcpDashboardOverviewLogic)

    const tiles: TileSpec[] = [
        {
            label: 'Sessions',
            metric: kpis.sessions,
            href: urls.mcpAnalyticsSessions(),
            format: formatNumber,
            color: 'blue',
            loading: kpisLoading,
            deltaKind: 'pct',
        },
        {
            label: 'Tool calls',
            metric: kpis.toolCalls,
            href: urls.mcpAnalyticsTools(),
            format: formatNumber,
            color: 'blue',
            loading: kpisLoading,
            deltaKind: 'pct',
        },
        {
            label: 'Error rate',
            metric: kpis.errorRatePct,
            href: urls.mcpAnalyticsSessions(),
            format: formatPercent,
            color: 'red',
            loading: kpisLoading,
            deltaKind: 'pp',
        },
        {
            label: 'p95 latency',
            metric: kpis.p95LatencyMs,
            href: urls.mcpAnalyticsTools(),
            format: formatMs,
            color: 'blue',
            loading: kpisLoading,
            deltaKind: 'ms',
        },
        {
            label: 'Task clusters',
            metric: intentClusterCount,
            href: urls.mcpAnalyticsTasks(),
            format: formatNumber,
            color: 'green',
            loading: false,
            deltaKind: 'count',
        },
    ]

    return (
        <div className="flex flex-col gap-[22px]">
            <BrandingStrip />
            <Block question="Is the MCP healthy right now?" title="Last 7 days vs prior 7 days">
                <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                    {tiles.map((tile) => (
                        <KPITile key={tile.label} tile={tile} />
                    ))}
                </div>
            </Block>
            <Block
                question="Which tools are the weak links?"
                title="Tool reliability matrix"
                headerRight={<span className="text-[11px] text-tertiary">Sorted by call volume</span>}
            >
                <ToolReliabilityMatrix rows={topToolRows} loading={toolRowsLoading} totalTools={toolRowsTotal} />
            </Block>
            <Block question="Which harnesses are calling the MCP?" title="Agent harnesses">
                <HarnessBreakdown rows={harnessRows} loading={harnessRawRowsLoading} />
            </Block>
            <Block
                question="How are agents actually using the MCP?"
                title="Agent journeys"
                headerRight={
                    <>
                        <span
                            className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                            style={{ background: '#EEEDFE', color: '#3C3489' }}
                        >
                            Top 10 paths
                        </span>
                        <span className="text-[11px] text-tertiary">Init → tool → tool → outcome</span>
                    </>
                }
            >
                <AgentJourneysBlock journey={dashboardJourney} />
            </Block>
            <Block question="Which sessions should I look at?" title="Notable sessions">
                <NotableSessionsTable sessions={notableSessions} loading={sessionRowsLoading} />
            </Block>
        </div>
    )
}

function BrandingStrip(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const projectName = currentTeam?.name ?? 'project'
    return (
        <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
                <span className="flex h-[22px] w-[22px] items-center justify-center rounded bg-warning text-white">
                    <IconBolt className="h-3 w-3" />
                </span>
                <span className="text-[13px] font-medium">PostHog for Agents</span>
                <span
                    className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                    style={{ background: '#E6F1FB', color: '#0C447C' }}
                >
                    Preview
                </span>
            </div>
            <span className="text-[11px] text-tertiary">Project: {projectName} · mcp-server</span>
        </div>
    )
}

function Block({
    question,
    title,
    headerRight,
    children,
}: {
    question: string
    title: string
    headerRight?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col">
            <p className="mb-1 text-[11px] text-secondary">{question}</p>
            <div className="mb-3 flex items-center justify-between gap-2">
                <h1 className="text-sm font-medium">{title}</h1>
                {headerRight ? <div className="flex items-center gap-2">{headerRight}</div> : null}
            </div>
            {children}
        </section>
    )
}

function Card({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="rounded-lg border border-primary bg-surface-primary px-3.5 py-3">{children}</div>
}

type ErrorBucket = 'green' | 'amber' | 'red'

function errorBucket(pct: number): ErrorBucket {
    if (pct < 1) {
        return 'green'
    }
    if (pct <= 5) {
        return 'amber'
    }
    return 'red'
}

const ERROR_PILL_CLASS: Record<ErrorBucket, string> = {
    green: 'text-[#27500A] bg-[#EAF3DE]',
    amber: 'text-[#633806] bg-[#FAEEDA]',
    red: 'text-[#791F1F] bg-[#FCEBEB]',
}

function ErrorRatePill({ pct }: { pct: number }): JSX.Element {
    const bucket = errorBucket(pct)
    return (
        <span
            className={`inline-flex h-[14px] items-center justify-center rounded-[3px] px-1.5 text-[10px] font-medium ${ERROR_PILL_CLASS[bucket]}`}
        >
            {pct.toFixed(pct >= 10 ? 0 : 1)}%
        </span>
    )
}

function ToolRowItem({ row, maxVolume, isLast }: { row: ToolRow; maxVolume: number; isLast: boolean }): JSX.Element {
    const callsPct = maxVolume ? (row.total_calls / maxVolume) * 100 : 0
    const errorsPct = maxVolume ? (row.errors / maxVolume) * 100 : 0
    const successPct = Math.max(callsPct - errorsPct, 0)
    const isWeak = row.error_rate_pct > 5
    const nameClass = isWeak ? 'text-[#791F1F]' : 'text-primary'
    // Weak tools get a washed-pink success bar to signal trouble even before the eye lands on the pill.
    const successFill = isWeak ? '#F7C1C1' : '#B5D4F4'
    return (
        <div
            className="grid items-center gap-2.5 py-1.5"
            style={{
                gridTemplateColumns: '140px 1fr 60px 56px',
                borderBottom: isLast ? 'none' : '0.5px solid var(--color-border-tertiary)',
            }}
        >
            <Link
                to={urls.mcpAnalyticsTool(row.tool)}
                className={`truncate font-mono text-xs ${nameClass}`}
                title={row.tool}
            >
                {row.tool}
            </Link>
            <div
                className="relative flex h-[14px] overflow-hidden rounded-[3px] bg-surface-secondary"
                title={`${row.total_calls} calls · ${row.errors} errors`}
            >
                <div className="h-full" style={{ width: `${successPct}%`, background: successFill }} />
                <div className="h-full bg-[#F09595]" style={{ width: `${errorsPct}%` }} />
            </div>
            {row.error_rate_pct >= 1 ? (
                <ErrorRatePill pct={row.error_rate_pct} />
            ) : (
                <span className="text-right text-[11px] font-mono text-secondary">
                    {row.error_rate_pct.toFixed(1)}%
                </span>
            )}
            <span className="text-right font-mono text-xs text-primary">
                {row.p95_duration_ms ? `${Math.round(row.p95_duration_ms)}ms` : '—'}
            </span>
        </div>
    )
}

function ToolReliabilityMatrix({
    rows,
    loading,
    totalTools,
}: {
    rows: ToolRow[]
    loading: boolean
    totalTools: number
}): JSX.Element {
    const maxVolume = rows.length ? Math.max(...rows.map((r) => r.total_calls)) : 0

    return (
        <Card>
            <div
                className="grid items-center gap-2.5 pb-1.5 text-[11px] text-secondary"
                style={{
                    gridTemplateColumns: '140px 1fr 60px 56px',
                    borderBottom: '0.5px solid var(--color-border-secondary)',
                }}
            >
                <span>Tool</span>
                <span>
                    <span className="text-[#185FA5]">Calls</span>
                    <span className="mx-1">·</span>
                    <span className="text-[#A32D2D]">errors</span>
                </span>
                <span>Err</span>
                <span className="text-right">p95</span>
            </div>
            {loading && rows.length === 0 ? (
                <div className="space-y-2 py-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-3.5 w-full" />
                    ))}
                </div>
            ) : rows.length === 0 ? (
                <div className="py-6 text-center text-[12px] text-secondary">No tool calls yet.</div>
            ) : (
                rows.map((row, i) => (
                    <ToolRowItem key={row.tool} row={row} maxVolume={maxVolume} isLast={i === rows.length - 1} />
                ))
            )}
            {rows.length > 0 && (
                <div className="mt-1.5 flex justify-end">
                    {(() => {
                        // Worst tool = highest error_rate_pct with at least 1 error. Falls back to View all when nothing failed.
                        const worst = [...rows]
                            .filter((r) => r.errors > 0)
                            .sort((a, b) => b.error_rate_pct - a.error_rate_pct || b.total_calls - a.total_calls)[0]
                        if (worst) {
                            return (
                                <Link
                                    to={`${urls.mcpAnalyticsTools()}?tool=${encodeURIComponent(worst.tool)}`}
                                    className="text-[11px]"
                                >
                                    Investigate {worst.tool} failures ↗
                                </Link>
                            )
                        }
                        return (
                            <Link to={urls.mcpAnalyticsTools()} className="text-[11px]">
                                View all {totalTools} tools ↗
                            </Link>
                        )
                    })()}
                </div>
            )}
        </Card>
    )
}

function describeLeakSteps(steps: readonly (string | null)[]): string {
    const named = steps.filter((s): s is string => s !== null)
    if (named.length === 0) {
        return '(empty path)'
    }
    return named.join(' → ')
}

function AgentJourneysBlock({ journey }: { journey: DashboardJourney }): JSX.Element {
    const { paths, totalSessions, leak, singleToolSessions } = journey

    if (paths.length === 0) {
        // No multi-tool journeys to plot. If there's traffic at all, say so explicitly —
        // otherwise nudge the user toward recomputing the intent clusters.
        if (singleToolSessions > 0) {
            return (
                <Card>
                    <div className="py-6 text-center text-[12px] text-secondary">
                        Most sessions only called one tool — no multi-step journeys to visualize yet.
                        <br />
                        <span className="text-tertiary">
                            {singleToolSessions} single-tool session{singleToolSessions === 1 ? '' : 's'} tracked.
                        </span>
                    </div>
                </Card>
            )
        }
        return (
            <Card>
                <div className="py-6 text-center text-[12px] text-secondary">
                    No clustered journeys yet — recompute the intent clusters to populate this view.
                </div>
            </Card>
        )
    }

    const journeysSessions = paths.reduce((acc, p) => acc + p.count, 0)

    return (
        <Card>
            <div className="mb-2 text-[11px] text-secondary">
                {journeysSessions} session{journeysSessions === 1 ? '' : 's'} · top {paths.length} journey
                {paths.length === 1 ? '' : 's'}
                {singleToolSessions > 0 ? (
                    <span className="text-tertiary">
                        {' '}
                        · {singleToolSessions} single-tool session{singleToolSessions === 1 ? '' : 's'} hidden
                    </span>
                ) : null}
            </div>
            <JourneySankey
                paths={paths}
                totalSessions={totalSessions}
                leak={leak}
                showLeakSentence={false}
                width={640}
                height={280}
                columnLabels={[]}
                unifyOutcomes
            />
            <LeakCallout leak={leak} totalSessions={totalSessions} />
        </Card>
    )
}

const HARNESS_GRID_TEMPLATE = '160px 1fr 56px 56px'

function HarnessBreakdown({ rows, loading }: { rows: HarnessRow[]; loading: boolean }): JSX.Element {
    const maxCalls = rows.length ? Math.max(...rows.map((r) => r.total_calls)) : 0
    const totalCalls = rows.reduce((acc, r) => acc + r.total_calls, 0)

    return (
        <Card>
            <div
                className="grid items-center gap-2.5 pb-1.5 text-[11px] text-secondary"
                style={{
                    gridTemplateColumns: HARNESS_GRID_TEMPLATE,
                    borderBottom: '0.5px solid var(--color-border-secondary)',
                }}
            >
                <span>Harness</span>
                <span>
                    <span className="text-[#185FA5]">Calls</span>
                    <span className="mx-1">·</span>
                    <span className="text-[#A32D2D]">errors</span>
                </span>
                <span>Err</span>
                <span className="text-right">Share</span>
            </div>
            {loading && rows.length === 0 ? (
                <div className="space-y-2 py-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-3.5 w-full" />
                    ))}
                </div>
            ) : rows.length === 0 ? (
                <div className="py-6 text-center text-[12px] text-secondary">No harness data yet.</div>
            ) : (
                rows.map((row, i) => {
                    const callsPct = maxCalls ? (row.total_calls / maxCalls) * 100 : 0
                    const errorsPct = maxCalls ? (row.errors / maxCalls) * 100 : 0
                    const successPct = Math.max(callsPct - errorsPct, 0)
                    const share = totalCalls ? (row.total_calls / totalCalls) * 100 : 0
                    const tooltip = row.raw_clients.slice(0, 8).join(', ')
                    return (
                        <div
                            key={row.category}
                            className="grid items-center gap-2.5 py-1.5"
                            style={{
                                gridTemplateColumns: HARNESS_GRID_TEMPLATE,
                                borderBottom:
                                    i === rows.length - 1 ? 'none' : '0.5px solid var(--color-border-tertiary)',
                            }}
                        >
                            <HarnessPill category={row.category} title={tooltip} />
                            <div
                                className="relative flex h-[14px] overflow-hidden rounded-[3px] bg-surface-secondary"
                                title={`${row.total_calls} calls · ${row.errors} errors · ${row.sessions} sessions`}
                            >
                                <div className="h-full bg-[#B5D4F4]" style={{ width: `${successPct}%` }} />
                                <div className="h-full bg-[#F09595]" style={{ width: `${errorsPct}%` }} />
                            </div>
                            <ErrorRatePill pct={row.error_rate_pct} />
                            <span className="text-right font-mono text-xs text-primary">
                                {share.toFixed(share >= 10 ? 0 : 1)}%
                            </span>
                        </div>
                    )
                })
            )}
        </Card>
    )
}

function LeakCallout({ leak, totalSessions }: { leak: DashboardJourney['leak']; totalSessions: number }): JSX.Element {
    if (!leak) {
        return (
            <div className="mt-3 flex items-center justify-between border-t border-tertiary pt-2.5 text-[11px] text-secondary">
                <span>Every top path completed without an error this period.</span>
            </div>
        )
    }

    const pct = totalSessions > 0 ? Math.round((leak.count / totalSessions) * 1000) / 10 : 0
    return (
        <div className="mt-3 flex items-center justify-between gap-3 border-t border-tertiary pt-2.5 text-[11px]">
            <span className="truncate text-secondary">
                The {describeLeakSteps(leak.steps)} loop drains{' '}
                <span className="font-medium text-[#791F1F]">
                    {leak.count} session{leak.count === 1 ? '' : 's'} ({pct}%)
                </span>{' '}
                into {leak.outcome === 'error' ? 'Error / Abandoned' : 'Other'} — the single biggest leak.
            </span>
            <Link to={urls.mcpAnalyticsSessions()} className="shrink-0 whitespace-nowrap text-[11px]">
                See {leak.count} sessions ↗
            </Link>
        </div>
    )
}


function truncateSessionId(id: string): string {
    if (id.length <= 12) {
        return id
    }
    return `${id.slice(0, 4)}…${id.slice(-4)}`
}

function formatDuration(seconds: number): string {
    if (!seconds || !isFinite(seconds)) {
        return '—'
    }
    if (seconds < 60) {
        return `${seconds}s`
    }
    return humanFriendlyDuration(seconds, { secondsPrecision: 0 })
}

function StatusPill({ errorRatePct }: { errorRatePct: number }): JSX.Element {
    if (errorRatePct >= 100) {
        return (
            <span className="inline-flex h-[14px] items-center rounded-[3px] bg-[#FCEBEB] px-1.5 text-[10px] font-medium text-[#791F1F]">
                100% err
            </span>
        )
    }
    if (errorRatePct > 0) {
        const bucket = errorBucket(errorRatePct)
        return (
            <span
                className={`inline-flex h-[14px] items-center rounded-[3px] px-1.5 text-[10px] font-medium ${ERROR_PILL_CLASS[bucket]}`}
            >
                {errorRatePct.toFixed(errorRatePct >= 10 ? 0 : 1)}% err
            </span>
        )
    }
    return (
        <span className="inline-flex h-[14px] items-center rounded-[3px] bg-[#EAF3DE] px-1.5 text-[10px] font-medium text-[#27500A]">
            Success
        </span>
    )
}

const NOTABLE_GRID_TEMPLATE = '22% 12% 14% 18% 1fr'

function NotableSessionsTable({ sessions, loading }: { sessions: NotableSession[]; loading: boolean }): JSX.Element {
    return (
        <Card>
            <div
                className="grid items-center gap-2.5 pb-1.5 text-[11px] text-secondary"
                style={{
                    gridTemplateColumns: NOTABLE_GRID_TEMPLATE,
                    borderBottom: '0.5px solid var(--color-border-secondary)',
                }}
            >
                <span>Session</span>
                <span>Calls</span>
                <span>Duration</span>
                <span>Status</span>
                <span>Why notable</span>
            </div>
            {loading && sessions.length === 0 ? (
                <div className="space-y-2 py-3">
                    {Array.from({ length: 4 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-3.5 w-full" />
                    ))}
                </div>
            ) : sessions.length === 0 ? (
                <div className="py-6 text-center text-[12px] text-secondary">
                    No notable sessions in the last 7 days.
                </div>
            ) : (
                sessions.map((entry, i) => (
                    <div
                        key={entry.session.session_id}
                        className="grid items-center gap-2.5 py-1.5"
                        style={{
                            gridTemplateColumns: NOTABLE_GRID_TEMPLATE,
                            borderBottom:
                                i === sessions.length - 1 ? 'none' : '0.5px solid var(--color-border-tertiary)',
                        }}
                    >
                        <Link
                            to={urls.mcpAnalyticsSessions()}
                            className="truncate font-mono text-[11px]"
                            title={entry.session.session_id}
                        >
                            {truncateSessionId(entry.session.session_id)}
                        </Link>
                        <span className="text-[11px]">{entry.session.tool_calls}</span>
                        <span className="text-[11px]">{formatDuration(entry.session.duration_seconds)}</span>
                        <StatusPill errorRatePct={entry.session.error_rate_pct} />
                        <span className="truncate text-[11px] text-primary" title={entry.label}>
                            {entry.label}
                        </span>
                    </div>
                ))
            )}
            {sessions.length > 0 && (
                <div className="mt-1.5 flex justify-end">
                    <Link to={urls.mcpAnalyticsSessions()} className="text-[10px]">
                        Open all flagged sessions in Sessions tab ↗
                    </Link>
                </div>
            )}
        </Card>
    )
}
