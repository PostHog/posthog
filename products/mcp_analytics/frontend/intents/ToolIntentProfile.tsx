import { LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import { urls } from 'scenes/urls'

import type {
    MCPIntentOutlierItem,
    MCPIntentTopicItem,
    MCPIntentTopicRef,
    MCPToolIntentProfileQueryResponse,
} from '~/queries/schema/schema-general'

import { formatNumber } from '../dashboard/formatters'

const BAND_LABEL: Record<string, { label: string; tagType: 'success' | 'warning' | 'danger' }> = {
    consolidated: { label: 'Consolidated', tagType: 'success' },
    mixed: { label: 'Mixed', tagType: 'warning' },
    spread: { label: 'Spread', tagType: 'danger' },
}

function Card({ title, help, children }: { title: string; help?: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex min-h-[10rem] flex-col gap-2 rounded border bg-bg-light p-3" data-quill>
            <div className="flex items-center gap-1 text-xs font-medium uppercase text-secondary">
                {title}
                {help ? (
                    <Tooltip title={help}>
                        <span className="cursor-help">ⓘ</span>
                    </Tooltip>
                ) : null}
            </div>
            {children}
        </div>
    )
}

function TrendArrow({ trendPp }: { trendPp: number | null }): JSX.Element | null {
    if (trendPp === null) {
        return <span className="text-xs text-secondary">new</span>
    }
    if (Math.abs(trendPp) < 0.05) {
        return <span className="text-xs text-secondary">flat</span>
    }
    return (
        <span className={`text-xs ${trendPp > 0 ? 'text-success' : 'text-danger'}`}>
            {trendPp > 0 ? '▲' : '▼'} {Math.abs(trendPp).toFixed(1)} pp
        </span>
    )
}

function TopicRow({ topic, toolName }: { topic: MCPIntentTopicItem; toolName: string }): JSX.Element {
    return (
        <li className="flex items-center gap-2 text-sm">
            <div className="min-w-0 flex-1">
                <LinkPrimitive
                    to={urls.mcpAnalyticsIntentMap({ tool: toolName, topic: topic.topic_id })}
                    className="block truncate"
                >
                    {topic.label}
                </LinkPrimitive>
                <div className="flex items-center gap-2 text-xs text-secondary">
                    <span>{topic.share_pct.toFixed(1)}%</span>
                    <TrendArrow trendPp={topic.trend_pp} />
                </div>
            </div>
            {topic.sparkline?.length ? (
                <div className="w-24 shrink-0">
                    <Sparkline data={topic.sparkline} type="bar" className="h-6" name="calls" />
                </div>
            ) : null}
        </li>
    )
}

function DriftGroup({
    title,
    refs,
    toolName,
}: {
    title: string
    refs: MCPIntentTopicRef[]
    toolName: string
}): JSX.Element | null {
    if (refs.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-1">
            <div className="text-xs text-secondary">{title}</div>
            <div className="flex flex-wrap gap-1">
                {refs.map((ref) => (
                    <LinkPrimitive
                        key={ref.topic_id}
                        to={urls.mcpAnalyticsIntentMap({ tool: toolName, topic: ref.topic_id })}
                    >
                        <LemonTag>
                            {ref.label} · {ref.share_pct.toFixed(0)}%
                            {ref.previous_share_pct !== null ? ` (was ${ref.previous_share_pct.toFixed(0)}%)` : ''}
                        </LemonTag>
                    </LinkPrimitive>
                ))}
            </div>
        </div>
    )
}

function OutlierRow({ outlier }: { outlier: MCPIntentOutlierItem }): JSX.Element {
    return (
        <li className="text-sm">
            <div className="break-words">{outlier.intent_text}</div>
            <div className="text-xs text-secondary">{formatNumber(outlier.calls)} calls</div>
        </li>
    )
}

/** The four things a tool page says about intent: focus, top topics, drift, outliers. */
export function ToolIntentProfile({
    toolName,
    profile,
    loading,
}: {
    toolName: string
    profile: MCPToolIntentProfileQueryResponse | null
    loading: boolean
}): JSX.Element {
    if (loading && !profile) {
        return (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
                {[0, 1, 2, 3].map((i) => (
                    <LemonSkeleton key={i} className="h-40" />
                ))}
            </div>
        )
    }
    if (!profile || profile.coverage.calls_with_intent === 0) {
        return (
            <div className="text-sm text-secondary" data-attr="mcp-tool-intent-profile-empty">
                No intent topics for this tool in the selected range. Topics appear after the nightly run has embedded
                and clustered the intents agents send with their calls.
            </div>
        )
    }
    const band = BAND_LABEL[profile.focus.band] ?? BAND_LABEL.mixed
    const drift = profile.drift
    const hasDrift = drift.new.length + drift.growing.length + drift.shrinking.length + drift.gone.length > 0
    const mapUrl = urls.mcpAnalyticsIntentMap({ tool: toolName })

    return (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4" data-attr="mcp-tool-intent-profile">
            <Card
                title="Focus"
                help="1 minus the normalised entropy of calls across topics. 1 means every call serves one topic; 0 an even spread."
            >
                <div className="flex items-baseline gap-2">
                    <span className="text-3xl font-semibold">{profile.focus.score.toFixed(2)}</span>
                    <LemonTag type={band.tagType}>{band.label}</LemonTag>
                </div>
                <div className="text-xs text-secondary">
                    {formatNumber(profile.coverage.calls_assigned)} of{' '}
                    {formatNumber(profile.coverage.calls_with_intent)} calls with an intent have a topic (
                    {profile.coverage.assigned_pct.toFixed(0)}%)
                </div>
                <LinkPrimitive to={mapUrl} className="text-xs">
                    Open the intent map for this tool
                </LinkPrimitive>
            </Card>
            <Card
                title="Top topics"
                help="Share of this tool's intent-carrying calls, and the change versus the previous window of the same length."
            >
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                    {profile.results.map((topic) => (
                        <TopicRow key={topic.topic_id} topic={topic} toolName={toolName} />
                    ))}
                </ul>
            </Card>
            <Card
                title="Drift"
                help="Topics whose share moved by at least 1.5 times versus the previous window, with at least 5 calls."
            >
                {hasDrift ? (
                    <div className="flex flex-col gap-2">
                        <DriftGroup title="New" refs={drift.new} toolName={toolName} />
                        <DriftGroup title="Growing" refs={drift.growing} toolName={toolName} />
                        <DriftGroup title="Shrinking" refs={drift.shrinking} toolName={toolName} />
                        <DriftGroup title="Gone" refs={drift.gone} toolName={toolName} />
                    </div>
                ) : (
                    <div className="text-sm text-secondary">No topic moved enough to count as drift.</div>
                )}
            </Card>
            <Card
                title="Outliers"
                help="Intents further from their nearest topic than that topic's 95th percentile member."
            >
                {profile.outliers.length === 0 ? (
                    <div className="text-sm text-secondary">No outlier intents in this range.</div>
                ) : (
                    <ul className="m-0 flex list-none flex-col gap-2 p-0">
                        {profile.outliers.slice(0, 5).map((outlier) => (
                            <OutlierRow key={outlier.intent_hash} outlier={outlier} />
                        ))}
                    </ul>
                )}
            </Card>
        </div>
    )
}
