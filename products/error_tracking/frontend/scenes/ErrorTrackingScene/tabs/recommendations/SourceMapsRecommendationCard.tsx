import { LemonButton, Link } from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber } from 'lib/utils'
import { urls } from 'scenes/urls'

import { RecommendationCard } from './RecommendationCard'
import type { SourceMapsRecommendation } from './types'

const SOURCE_MAPS_DOCS_URL = 'https://posthog.com/docs/error-tracking/upload-source-maps'

export function SourceMapsRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: SourceMapsRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    const { total_frames, unresolved_frames, unresolved_pct, lookback_days } = recommendation.meta
    const isFirstLoad = recommendation.computed_at === null

    if (isFirstLoad) {
        return (
            <RecommendationCard
                recommendationId={recommendation.id}
                title="Missing source maps"
                description="Upload source maps so JavaScript stack traces show your original source code."
                dismissed={dismissed}
            />
        )
    }

    const percent = Math.round((unresolved_pct ?? 0) * 100)

    return (
        <RecommendationCard
            recommendationId={recommendation.id}
            title="Missing source maps"
            description="Upload source maps so JavaScript stack traces show your original source code."
            dismissed={dismissed}
        >
            <div className="flex flex-col gap-3">
                <div className="text-sm">
                    <span className="font-semibold">{percent}%</span>
                    <span className="text-secondary">
                        {' '}
                        of JavaScript frames in the last {lookback_days} days couldn't be resolved (
                        {humanFriendlyLargeNumber(unresolved_frames)} of {humanFriendlyLargeNumber(total_frames)}).
                    </span>
                </div>
                <div className="text-xs text-secondary">
                    Without source maps, stack traces point at minified bundles instead of your original code, which
                    makes debugging much harder.
                </div>
                <div className="flex items-center gap-2">
                    <LemonButton
                        size="small"
                        type="primary"
                        to={urls.settings('environment-error-tracking', 'error-tracking-symbol-sets')}
                    >
                        Manage symbol sets
                    </LemonButton>
                    <Link to={SOURCE_MAPS_DOCS_URL} target="_blank" className="text-xs">
                        Read the docs
                    </Link>
                </div>
            </div>
        </RecommendationCard>
    )
}
