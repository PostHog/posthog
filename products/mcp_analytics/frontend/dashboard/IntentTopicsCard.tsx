import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import { urls } from 'scenes/urls'

import type { MCPIntentTopicItem, MCPIntentTopicsQueryResponse } from '~/queries/schema/schema-general'

import { IntentTopicsScopeNote } from '../intents/IntentTopicsScopeNote'
import { TopicTrend } from '../intents/TopicTrend'
import { formatNumber } from './formatters'

/** "What agents use your server for": the top intent topics with share and trend, and a way into the map. */
export function IntentTopicsCard({
    topics,
    loading,
    failed,
    onRetry,
    dateFrom,
    dateTo,
    filtersIgnored,
}: {
    topics: MCPIntentTopicsQueryResponse | null
    loading: boolean
    failed: boolean
    onRetry: () => void
    dateFrom: string | null
    dateTo: string | null
    filtersIgnored: boolean
}): JSX.Element {
    const items: MCPIntentTopicItem[] = topics?.results ?? []
    const maxShare = Math.max(1, ...items.map((item) => item.share_pct))
    return (
        <div
            className="flex min-w-0 flex-col gap-3 rounded border bg-bg-light p-3"
            data-attr="mcp-dashboard-intent-topics"
            data-quill
        >
            <div className="flex items-center justify-between gap-2">
                <div className="flex flex-col">
                    <h3 className="mb-0 text-sm font-semibold">What agents use your server for</h3>
                    {topics && !failed ? (
                        <span className="text-xs text-secondary">
                            <span translate="no">{formatNumber(topics.coverage.calls_assigned)}</span>
                            <span> of </span>
                            <span translate="no">{formatNumber(topics.coverage.calls_with_intent)}</span>
                            <span> calls with an intent have a topic</span>
                        </span>
                    ) : null}
                </div>
                <LinkPrimitive
                    to={urls.mcpAnalyticsIntentMap({ dateFrom, dateTo })}
                    className="text-xs"
                    data-attr="mcp-dashboard-intent-topics-open-map"
                >
                    Open intent map
                </LinkPrimitive>
            </div>
            <IntentTopicsScopeNote filtersIgnored={filtersIgnored} dateFrom={dateFrom} dateTo={dateTo} />
            {failed && !loading ? (
                <div
                    className="flex items-center gap-2 text-sm text-secondary"
                    data-attr="mcp-dashboard-intent-topics-error"
                >
                    <span>Intent topics couldn't load.</span>
                    <LemonButton size="xsmall" type="secondary" onClick={onRetry}>
                        Try again
                    </LemonButton>
                </div>
            ) : loading && (!topics || failed) ? (
                <LemonSkeleton className="h-32" />
            ) : items.length === 0 ? (
                <div className="text-sm text-secondary">No intent topics yet for this date range.</div>
            ) : (
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                    {items.map((item) => (
                        <li key={item.topic_id} className="flex flex-col gap-0.5">
                            <div className="flex items-center justify-between gap-2 text-sm">
                                <LinkPrimitive
                                    to={urls.mcpAnalyticsIntentMap({ topic: item.topic_id, dateFrom, dateTo })}
                                    className="min-w-0 truncate"
                                >
                                    {item.label}
                                </LinkPrimitive>
                                <div className="flex shrink-0 items-center gap-2">
                                    <span className="text-xs text-secondary" translate="no">
                                        {item.share_pct.toFixed(1)}%
                                    </span>
                                    <TopicTrend trendPp={item.trend_pp} />
                                </div>
                            </div>
                            <div className="h-1.5 w-full rounded bg-fill-highlight-100">
                                <div
                                    className="h-1.5 rounded bg-accent"
                                    style={{ width: `${(100 * item.share_pct) / maxShare}%` }}
                                />
                            </div>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}
