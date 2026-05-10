import { combineUrl } from 'kea-router'

import { Link } from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ActivityTab, PropertyFilterType, PropertyOperator } from '~/types'

import { RecommendationCard } from './RecommendationCard'
import type { IngestionFailuresRecommendation } from './types'

const FAILURES_QUERY = {
    kind: 'DataTableNode' as const,
    full: true,
    source: {
        kind: 'EventsQuery' as const,
        select: ['*', 'event', 'person', 'timestamp', 'properties.$cymbal_errors'],
        event: '$exception',
        after: '-24h',
        orderBy: ['timestamp DESC'],
        properties: [
            {
                key: '$cymbal_errors',
                value: 'is_set',
                operator: PropertyOperator.IsSet,
                type: PropertyFilterType.Event,
            },
        ],
    },
    propertiesViaUrl: true,
    showSavedQueries: true,
    showPersistentColumnConfigurator: true,
}

function buildFailuresUrl(): string {
    return combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: FAILURES_QUERY }).url
}

export function IngestionFailuresRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: IngestionFailuresRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    const isFirstLoad = recommendation.computed_at === null

    if (isFirstLoad) {
        return (
            <RecommendationCard
                recommendationId={recommendation.id}
                title="Ingestion problems"
                description="Exceptions that hit errors during ingestion processing — they may be missing stack traces, source maps, or other context."
                dismissed={dismissed}
            />
        )
    }

    const { count_24h, count_1h, top_causes } = recommendation.meta

    if (count_24h === 0) {
        return (
            <RecommendationCard recommendationId={recommendation.id} title="Ingestion problems" dismissed={dismissed}>
                <div className="text-sm text-secondary">No ingestion problems in the last 24 hours — nice work!</div>
            </RecommendationCard>
        )
    }

    const failuresUrl = buildFailuresUrl()

    return (
        <RecommendationCard
            recommendationId={recommendation.id}
            title="Ingestion problems"
            description="Exceptions that hit errors during ingestion processing — they may be missing stack traces, source maps, or other context."
            dismissed={dismissed}
        >
            <div className="flex flex-col gap-3">
                <div className="grid grid-cols-2 gap-3">
                    <div className="border rounded-md p-3 bg-surface-secondary">
                        <div className="text-xs uppercase tracking-wide text-muted font-semibold">Last 24h</div>
                        <div className="text-xl font-semibold mt-1">{humanFriendlyLargeNumber(count_24h)}</div>
                        <div className="text-xs text-secondary">exceptions failed to ingest</div>
                    </div>
                    <div className="border rounded-md p-3 bg-surface-secondary">
                        <div className="text-xs uppercase tracking-wide text-muted font-semibold">Last 1h</div>
                        <div className="text-xl font-semibold mt-1">{humanFriendlyLargeNumber(count_1h)}</div>
                        <div className="text-xs text-secondary">exceptions failed to ingest</div>
                    </div>
                </div>

                {top_causes.length > 0 && (
                    <div>
                        <div className="text-xs uppercase tracking-wide text-muted font-semibold mb-2">
                            {top_causes.length === 1 ? 'Most common cause' : 'Most common causes'}
                        </div>
                        <ul className="flex flex-col gap-1 m-0 p-0 list-none">
                            {top_causes.map((cause, idx) => (
                                <li
                                    key={`${idx}-${cause.cause}`}
                                    className="flex items-start justify-between gap-3 text-sm"
                                >
                                    <span className="font-mono text-xs truncate" title={cause.cause}>
                                        {cause.cause}
                                    </span>
                                    <span className="text-xs text-secondary whitespace-nowrap shrink-0">
                                        {humanFriendlyLargeNumber(cause.occurrences)}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}

                <div>
                    <Link to={failuresUrl} className="text-sm">
                        View failures →
                    </Link>
                </div>
            </div>
        </RecommendationCard>
    )
}
