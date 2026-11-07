import { LemonSkeleton } from '@posthog/lemon-ui'

import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import { urls } from 'scenes/urls'

import type { MCPIntentTopicItem, MCPIntentTopicsQueryResponse } from '~/queries/schema/schema-general'

import { formatNumber } from './formatters'

function Trend({ trendPp }: { trendPp: number | null }): JSX.Element {
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

/** "What agents use your server for": the top intent topics with share and trend, and a way into the map. */
export function IntentTopicsCard({
    topics,
    loading,
}: {
    topics: MCPIntentTopicsQueryResponse | null
    loading: boolean
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
                    {topics ? (
                        <span className="text-xs text-secondary">
                            {formatNumber(topics.coverage.calls_assigned)} of{' '}
                            {formatNumber(topics.coverage.calls_with_intent)} calls with an intent have a topic
                        </span>
                    ) : null}
                </div>
                <LinkPrimitive
                    to={urls.mcpAnalyticsIntentMap()}
                    className="text-xs"
                    data-attr="mcp-dashboard-intent-topics-open-map"
                >
                    Open intent map
                </LinkPrimitive>
            </div>
            {loading && !topics ? (
                <LemonSkeleton className="h-32" />
            ) : items.length === 0 ? (
                <div className="text-sm text-secondary">No intent topics yet for this date range.</div>
            ) : (
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                    {items.map((item) => (
                        <li key={item.topic_id} className="flex flex-col gap-0.5">
                            <div className="flex items-center justify-between gap-2 text-sm">
                                <LinkPrimitive
                                    to={urls.mcpAnalyticsIntentMap({ topic: item.topic_id })}
                                    className="min-w-0 truncate"
                                >
                                    {item.label}
                                </LinkPrimitive>
                                <div className="flex shrink-0 items-center gap-2">
                                    <span className="text-xs text-secondary">{item.share_pct.toFixed(1)}%</span>
                                    <Trend trendPp={item.trend_pp} />
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
