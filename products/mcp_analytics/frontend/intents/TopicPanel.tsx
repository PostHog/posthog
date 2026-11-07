import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'

import { formatNumber } from '../dashboard/formatters'
import { mcpToolReportUrl } from '../mcpAnalyticsToolQualityLogic'
import { TOPIC_POINTS_PAGE_SIZE, intentMapLogic } from './intentMapLogic'

/** Right-hand panel: the topic list as a legend, or the selected topic with its intents. */
export function TopicPanel(): JSX.Element {
    const {
        topics,
        selectedTopic,
        selectedTopicPoints,
        visibleTopicPoints,
        topicId,
        totalPoints,
        points,
        mapLoading,
        dateFilter,
        topicColor,
    } = useValues(intentMapLogic)
    const { selectTopic, setTopicId, showMoreTopicPoints } = useActions(intentMapLogic)
    const hiddenTopicPoints = selectedTopicPoints.length - visibleTopicPoints.length

    if (selectedTopic) {
        return (
            <div className="flex h-full min-h-0 flex-col gap-3" data-attr="mcp-intent-topic-panel">
                <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 flex-col gap-1">
                        <div className="flex items-center gap-2">
                            <span
                                className="inline-block h-3 w-3 shrink-0 rounded-full"
                                style={{ background: topicColor(selectedTopic.topic_id) }}
                            />
                            <h3 className="mb-0 truncate text-base font-semibold">{selectedTopic.label}</h3>
                        </div>
                        {selectedTopic.summary ? (
                            <p className="mb-0 text-sm text-secondary">{selectedTopic.summary}</p>
                        ) : null}
                        <div className="text-xs text-secondary">
                            <span translate="no">{formatNumber(selectedTopic.calls)}</span>
                            <span> calls · </span>
                            <span translate="no">{selectedTopic.share_pct.toFixed(1)}%</span>
                            <span> of calls with an intent</span>
                        </div>
                    </div>
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={() => (topicId ? setTopicId(null) : selectTopic(null))}
                    >
                        {topicId ? 'Show all topics' : 'Close'}
                    </LemonButton>
                </div>
                {!topicId ? (
                    <LemonButton
                        size="small"
                        type="primary"
                        onClick={() => setTopicId(selectedTopic.topic_id)}
                        data-attr="mcp-intent-topic-focus"
                    >
                        Show only this topic's intents
                    </LemonButton>
                ) : null}
                <div className="text-xs font-medium uppercase text-secondary">Intents in view, most called first</div>
                <ul className="m-0 flex min-h-0 flex-1 list-none flex-col gap-1 overflow-y-auto p-0">
                    {selectedTopicPoints.length === 0 ? (
                        <li className="text-sm text-secondary">
                            {mapLoading
                                ? 'Loading…'
                                : 'No intents of this topic in the current view. Drag on the map to zoom, or widen the date range.'}
                        </li>
                    ) : (
                        visibleTopicPoints.map((point) => (
                            <li key={point.intent_hash} className="rounded border px-2 py-1 text-sm">
                                <div className="break-words">{point.intent_text}</div>
                                <div className="flex flex-wrap items-center gap-1 text-xs text-secondary">
                                    <span>
                                        <span translate="no">{formatNumber(point.calls)}</span>
                                        <span> calls</span>
                                    </span>
                                    {point.tool ? (
                                        <LinkPrimitive to={mcpToolReportUrl(point.tool, dateFilter)}>
                                            {point.tool}
                                        </LinkPrimitive>
                                    ) : null}
                                    {point.is_outlier ? <LemonTag type="warning">outlier</LemonTag> : null}
                                </div>
                            </li>
                        ))
                    )}
                    {hiddenTopicPoints > 0 ? (
                        <li>
                            <LemonButton
                                size="small"
                                type="secondary"
                                fullWidth
                                center
                                onClick={() => showMoreTopicPoints()}
                                data-attr="mcp-intent-topic-show-more"
                            >
                                {`Show ${formatNumber(Math.min(hiddenTopicPoints, TOPIC_POINTS_PAGE_SIZE))} more of ${formatNumber(hiddenTopicPoints)}`}
                            </LemonButton>
                        </li>
                    ) : null}
                </ul>
            </div>
        )
    }

    return (
        <div className="flex h-full min-h-0 flex-col gap-2" data-attr="mcp-intent-topic-list">
            <div className="text-xs font-medium uppercase text-secondary">
                <span>Topics · </span>
                <span translate="no">{formatNumber(points.length)}</span>
                <span> of </span>
                <span translate="no">{formatNumber(totalPoints)}</span>
                <span> intents shown</span>
            </div>
            <ul className="m-0 flex min-h-0 flex-1 list-none flex-col gap-1 overflow-y-auto p-0">
                {topics.map((topic) => (
                    <li key={topic.topic_id}>
                        <button
                            type="button"
                            className="flex w-full items-center gap-2 rounded border px-2 py-1 text-left text-sm hover:bg-fill-highlight-50"
                            onClick={() => selectTopic(topic.topic_id)}
                            data-attr="mcp-intent-topic-row"
                        >
                            <span
                                className="inline-block h-3 w-3 shrink-0 rounded-full"
                                style={{ background: topicColor(topic.topic_id) }}
                            />
                            <span className="min-w-0 flex-1 truncate">{topic.label}</span>
                            <span className="shrink-0 text-xs text-secondary" translate="no">
                                {topic.share_pct.toFixed(1)}%
                            </span>
                        </button>
                    </li>
                ))}
            </ul>
        </div>
    )
}
