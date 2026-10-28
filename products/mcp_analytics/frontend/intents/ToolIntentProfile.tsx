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
import { TopicTrend } from './TopicTrend'

interface MapLinkContext {
    toolName: string
    dateFrom: string | null
    dateTo: string | null
}

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

function TopicRow({ topic, link }: { topic: MCPIntentTopicItem; link: MapLinkContext }): JSX.Element {
    return (
        <li className="flex flex-col gap-1 text-sm">
            <LinkPrimitive
                to={urls.mcpAnalyticsIntentMap({
                    tool: link.toolName,
                    topic: topic.topic_id,
                    dateFrom: link.dateFrom,
                    dateTo: link.dateTo,
                })}
                className="line-clamp-2 break-words"
            >
                {topic.label}
            </LinkPrimitive>
            <div className="flex items-center gap-2 text-xs text-secondary">
                <span className="shrink-0" translate="no">
                    {topic.share_pct.toFixed(1)}%
                </span>
                <TopicTrend trendPp={topic.trend_pp} />
                {topic.sparkline?.length ? (
                    // The sparkline sizes itself by bucket count; w-full keeps it inside the card.
                    <Sparkline data={topic.sparkline} type="bar" className="h-5 w-full min-w-0 flex-1" name="calls" />
                ) : null}
            </div>
        </li>
    )
}

function DriftGroup({
    title,
    refs,
    link,
}: {
    title: string
    refs: MCPIntentTopicRef[]
    link: MapLinkContext
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
                        to={urls.mcpAnalyticsIntentMap({
                            tool: link.toolName,
                            topic: ref.topic_id,
                            dateFrom: link.dateFrom,
                            dateTo: link.dateTo,
                        })}
                        className="max-w-full"
                    >
                        <LemonTag className="h-auto max-w-full whitespace-normal">
                            {/* One inline wrapper so the parts flow as text instead of as separate flex items. */}
                            <span>
                                <span>{ref.label}</span>
                                <span translate="no"> · {ref.share_pct.toFixed(0)}%</span>
                                {ref.previous_share_pct !== null ? (
                                    <>
                                        <span> (was </span>
                                        <span translate="no">{ref.previous_share_pct.toFixed(0)}%</span>
                                        <span>)</span>
                                    </>
                                ) : null}
                            </span>
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
            <div className="text-xs text-secondary">
                <span translate="no">{formatNumber(outlier.calls)}</span>
                <span> calls</span>
            </div>
        </li>
    )
}

/** The four things a tool page says about intent: focus, top topics, drift, outliers. */
export function ToolIntentProfile({
    toolName,
    dateFrom,
    dateTo,
    profile,
    loading,
}: {
    toolName: string
    dateFrom: string | null
    dateTo: string | null
    profile: MCPToolIntentProfileQueryResponse | null
    loading: boolean
}): JSX.Element {
    if (loading && !profile) {
        return (
            <div className="grid grid-cols-1 gap-4 @min-[48rem]/main-content:grid-cols-2 @min-[64rem]/main-content:grid-cols-4">
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
    // With no call assigned the backend still sends a 0 score, which would read as an even spread.
    const hasAssignedCalls = profile.coverage.calls_assigned > 0
    const drift = profile.drift
    const hasDrift = drift.new.length + drift.growing.length + drift.shrinking.length + drift.gone.length > 0
    const link: MapLinkContext = { toolName, dateFrom, dateTo }
    const mapUrl = urls.mcpAnalyticsIntentMap({ tool: toolName, dateFrom, dateTo })

    return (
        <div
            className="grid grid-cols-1 gap-4 @min-[48rem]/main-content:grid-cols-2 @min-[64rem]/main-content:grid-cols-4"
            data-attr="mcp-tool-intent-profile"
        >
            <Card
                title="Focus"
                help="1 minus the normalised entropy of calls across topics. 1 means every call serves one topic; 0 an even spread."
            >
                {hasAssignedCalls ? (
                    <div className="flex flex-wrap items-baseline gap-2">
                        <span className="text-3xl font-semibold" translate="no">
                            {profile.focus.score.toFixed(2)}
                        </span>
                        <LemonTag type={band.tagType}>{band.label}</LemonTag>
                    </div>
                ) : (
                    <div className="text-sm text-secondary" data-attr="mcp-tool-intent-profile-unassigned">
                        No calls have a topic yet, so there's no focus score. The nightly run assigns topics to new
                        intents.
                    </div>
                )}
                <div className="text-xs text-secondary">
                    <span translate="no">{formatNumber(profile.coverage.calls_assigned)}</span>
                    <span> of </span>
                    <span translate="no">{formatNumber(profile.coverage.calls_with_intent)}</span>
                    <span> calls with an intent have a topic (</span>
                    <span translate="no">{profile.coverage.assigned_pct.toFixed(0)}%</span>
                    <span>)</span>
                </div>
                <LinkPrimitive to={mapUrl} className="text-xs">
                    Open the intent map for this tool
                </LinkPrimitive>
            </Card>
            <Card
                title="Top topics"
                help="Share of this tool's intent-carrying calls, and the change versus the previous window of the same length."
            >
                {profile.results.length === 0 ? (
                    <div className="text-sm text-secondary">No topics yet for this tool in the selected range.</div>
                ) : (
                    <ul className="m-0 flex list-none flex-col gap-2 p-0">
                        {profile.results.map((topic) => (
                            <TopicRow key={topic.topic_id} topic={topic} link={link} />
                        ))}
                    </ul>
                )}
            </Card>
            <Card
                title="Drift"
                help="Topics whose share of calls with an intent moved by at least 1.5 times versus the previous window. A topic needs at least 5 calls to count."
            >
                {hasDrift ? (
                    <div className="flex flex-col gap-2">
                        <DriftGroup title="New" refs={drift.new} link={link} />
                        <DriftGroup title="Growing" refs={drift.growing} link={link} />
                        <DriftGroup title="Shrinking" refs={drift.shrinking} link={link} />
                        <DriftGroup title="Gone" refs={drift.gone} link={link} />
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
