import { useValues } from 'kea'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { Query } from '@posthog/query-frontend/Query/Query'

import { TZLabel } from 'lib/components/TZLabel'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { humanFriendlyDuration, humanFriendlyNumber } from 'lib/utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneExport } from '~/scenes/sceneTypes'

import { HarnessPill } from './dashboard/harness'
import {
    IntentCoverage,
    MCPAnalyticsToolDetailLogicProps,
    ToolSummary,
    mcpAnalyticsToolDetailLogic,
} from './mcpAnalyticsToolDetailLogic'
import { categorizeHarness } from './mcpDashboardOverviewLogic'

export const scene: SceneExport<MCPAnalyticsToolDetailLogicProps> = {
    component: MCPAnalyticsToolDetail,
    logic: mcpAnalyticsToolDetailLogic,
    paramsToProps: ({ params: { toolName } }) => ({
        toolName: decodeURIComponent(toolName ?? ''),
    }),
}

function percentDelta(current: number, previous: number): number | null {
    if (!previous) {
        return null
    }
    return ((current - previous) / previous) * 100
}

function DeltaTag({ value, invertColor = false }: { value: number | null; invertColor?: boolean }): JSX.Element | null {
    if (value == null || !isFinite(value) || Math.abs(value) < 1) {
        return null
    }
    const positive = value > 0
    // For error rate, "up" is bad — invert color semantics.
    const goodDirection = invertColor ? !positive : positive
    const Icon = positive ? IconArrowUp : IconArrowDown
    return (
        <span
            className={`inline-flex items-center gap-0.5 text-xs leading-none ${
                goodDirection ? 'text-success' : 'text-danger'
            }`}
        >
            <Icon className="text-sm" />
            {Math.abs(Math.round(value))}%
        </span>
    )
}

function Stat({
    label,
    value,
    delta,
    deltaInvertColor,
    loading,
    tooltip,
}: {
    label: string
    value: React.ReactNode
    delta?: number | null
    deltaInvertColor?: boolean
    loading?: boolean
    tooltip?: string
}): JSX.Element {
    const content = (
        <div className="flex flex-col gap-1 min-w-[110px]">
            <span className="text-[11px] uppercase tracking-wider text-secondary">{label}</span>
            {loading ? (
                <LemonSkeleton className="h-6 w-16" />
            ) : (
                <div className="flex items-baseline gap-2">
                    <span className="text-2xl font-semibold leading-none">{value}</span>
                    <DeltaTag value={delta ?? null} invertColor={deltaInvertColor} />
                </div>
            )}
        </div>
    )
    return tooltip ? <Tooltip title={tooltip}>{content}</Tooltip> : content
}

// Renderer for the "person" column in the Top users table. The query selects
// `argMax(tuple(distinct_id, person.created_at, person.properties), timestamp)`,
// which deserialises as a 3-element array. Wrap it back into the shape PersonDisplay expects.
const topUserPersonColumn = {
    title: 'User',
    render: function RenderPerson({ value }: { value: unknown }) {
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
            <PersonDisplay
                person={{ distinct_id: distinctId, properties: properties ?? {} }}
                withIcon
                noPopover={false}
            />
        )
    },
}

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <h2 className="text-base font-semibold mb-0">{title}</h2>
            {subtitle ? <span className="text-xs text-secondary">{subtitle}</span> : null}
        </div>
    )
}

function formatDurationMs(ms: number | null): string {
    if (ms == null) {
        return '—'
    }
    if (ms < 1000) {
        return `${Math.round(ms)} ms`
    }
    return humanFriendlyDuration(ms / 1000, { secondsFixed: 2 })
}

function StatStrip({ summary, loading }: { summary: ToolSummary | null; loading: boolean }): JSX.Element {
    const calls = summary?.calls ?? 0
    const errors = summary?.errors ?? 0
    const errorRate = calls ? (errors / calls) * 100 : 0
    const errorRatePrev = summary && summary.calls_prev ? (summary.errors_prev / summary.calls_prev) * 100 : 0
    return (
        <div className="flex flex-wrap items-end gap-x-10 gap-y-4 py-1">
            <Stat
                label="Calls"
                loading={loading}
                value={humanFriendlyNumber(calls)}
                delta={summary ? percentDelta(calls, summary.calls_prev) : null}
                tooltip="Last 7 days vs prior 7 days."
            />
            <Stat
                label="Error rate"
                loading={loading}
                value={`${errorRate.toFixed(1)}%`}
                delta={summary ? percentDelta(errorRate, errorRatePrev) : null}
                deltaInvertColor
                tooltip="Share of calls with $mcp_is_error = true."
            />
            <Stat label="p50 latency" loading={loading} value={formatDurationMs(summary?.p50_ms ?? null)} />
            <Stat label="p95 latency" loading={loading} value={formatDurationMs(summary?.p95_ms ?? null)} />
            <Stat label="Users" loading={loading} value={humanFriendlyNumber(summary?.users ?? 0)} />
            <Stat
                label="Sessions"
                loading={loading}
                value={humanFriendlyNumber(summary?.conversations ?? 0)}
                tooltip="Unique $mcp_session_id values, falling back to $session_id where missing."
            />
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
            <LemonMarkdown className="text-sm leading-snug" lowKeyHeadings>
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

export function MCPAnalyticsToolDetail({ toolName }: { toolName: string }): JSX.Element {
    const {
        summary,
        summaryLoading,
        descriptions,
        descriptionsLoading,
        callsTrendQuery,
        latencyTrendQuery,
        failuresQuery,
        sampleIntentsQuery,
        intentCoverage,
        intentCoverageLoading,
        neighborsBeforeQuery,
        neighborsAfterQuery,
        byHarnessQuery,
        topUsersQuery,
    } = useValues(mcpAnalyticsToolDetailLogic({ toolName }))

    return (
        <SceneContent>
            <SceneTitleSection
                name={toolName}
                description={null}
                resourceType={{ type: 'llm_analytics' }}
                actions={
                    <LemonButton
                        icon={<IconArrowLeft />}
                        type="secondary"
                        size="small"
                        to={urls.mcpAnalyticsToolQuality()}
                    >
                        Back to Tool quality
                    </LemonButton>
                }
            />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <DescriptionBlock descriptions={descriptions} loading={descriptionsLoading} />
                <StatStrip summary={summary} loading={summaryLoading} />
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader title="Reliability" subtitle="Last 7 days" />
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="flex flex-col bg-bg-light border rounded p-2" style={{ height: 240 }}>
                        <div className="text-secondary text-xs font-medium uppercase mb-1 px-2 pt-1">
                            Calls (broken down by error)
                        </div>
                        <div className="InsightCard__viz">
                            <Query query={callsTrendQuery} readOnly embedded />
                        </div>
                    </div>
                    <div className="flex flex-col bg-bg-light border rounded p-2" style={{ height: 240 }}>
                        <div className="text-secondary text-xs font-medium uppercase mb-1 px-2 pt-1">
                            Duration (p50 / p95)
                        </div>
                        <div className="InsightCard__viz">
                            <Query query={latencyTrendQuery} readOnly embedded />
                        </div>
                    </div>
                </div>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader title="Usage flow" />
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="flex flex-col gap-2 bg-bg-light border rounded p-3">
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-medium uppercase text-secondary">Sample intents</span>
                            <IntentCoverageTag coverage={intentCoverage} loading={intentCoverageLoading} />
                        </div>
                        <Query
                            query={sampleIntentsQuery}
                            readOnly
                            context={{
                                columns: {
                                    intent_source: { title: 'Intent source' },
                                },
                            }}
                        />
                    </div>
                    <div className="flex flex-col gap-3">
                        <div className="bg-bg-light border rounded p-3 flex flex-col gap-2">
                            <div className="flex items-center gap-1 text-xs font-medium uppercase text-secondary">
                                <IconArrowLeft className="text-base" />
                                Often called before (same conversation)
                            </div>
                            <Query
                                query={neighborsBeforeQuery}
                                readOnly
                                context={{ columns: { co_occurrences: { title: 'In same conversation' } } }}
                            />
                        </div>
                        <div className="bg-bg-light border rounded p-3 flex flex-col gap-2">
                            <div className="flex items-center gap-1 text-xs font-medium uppercase text-secondary">
                                <IconArrowRight className="text-base" />
                                Often called after (same conversation)
                            </div>
                            <Query
                                query={neighborsAfterQuery}
                                readOnly
                                context={{ columns: { co_occurrences: { title: 'In same conversation' } } }}
                            />
                        </div>
                    </div>
                </div>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader title="Who uses it" />
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="bg-bg-light border rounded p-3 flex flex-col gap-2">
                        <span className="text-xs font-medium uppercase text-secondary">By harness</span>
                        <Query
                            query={byHarnessQuery}
                            readOnly
                            context={{
                                columns: {
                                    harness: {
                                        title: 'Harness',
                                        render: function RenderHarness({ value }) {
                                            const raw = String(value ?? '')
                                            if (!raw) {
                                                return <span className="text-muted">Unknown</span>
                                            }
                                            return <HarnessPill category={categorizeHarness(raw)} title={raw} />
                                        },
                                    },
                                    error_rate_pct: { title: 'Error rate (%)' },
                                },
                            }}
                        />
                    </div>
                    <div className="bg-bg-light border rounded p-3 flex flex-col gap-2">
                        <span className="text-xs font-medium uppercase text-secondary">Top users</span>
                        <Query
                            query={topUsersQuery}
                            readOnly
                            context={{
                                columns: {
                                    person: topUserPersonColumn,
                                    error_rate_pct: { title: 'Error rate (%)' },
                                    last_seen: { title: 'Last seen' },
                                },
                            }}
                        />
                    </div>
                </div>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader
                    title="Failures"
                    subtitle="Top exception messages paired with this tool. Sourced from $exception events."
                />
                <Query query={failuresQuery} readOnly context={{ columns: { last_seen: { title: 'Last seen' } } }} />
            </div>
        </SceneContent>
    )
}

export default MCPAnalyticsToolDetail
