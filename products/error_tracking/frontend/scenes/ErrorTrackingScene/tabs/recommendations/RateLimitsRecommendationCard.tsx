import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { errorTrackingConfigurationSettingUrl } from './configurationSettingUrl'
import { ListRecommendationCard } from './ListRecommendationCard'
import { RATE_LIMIT_RECOMMENDATION_INFO, RateLimitsRecommendation } from './types'

const RATE_LIMITS_SETTINGS_URL = errorTrackingConfigurationSettingUrl('error-tracking-rate-limits')

export function RateLimitsRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: RateLimitsRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    const rateLimits = recommendation.meta.rate_limits ?? []

    if (rateLimits.length === 0) {
        if (recommendation.computed_at === null) {
            return (
                <ListRecommendationCard
                    recommendationId={recommendation.id}
                    title="Rate limits"
                    description="Protect ingestion from runaway exception volume."
                    dismissed={dismissed}
                    items={[]}
                    progressLabel="configured"
                />
            )
        }
        return null
    }

    const items = rateLimits.map((rateLimit) => {
        const info = RATE_LIMIT_RECOMMENDATION_INFO[rateLimit.key]
        return {
            key: rateLimit.key,
            enabled: rateLimit.enabled,
            name: info.name,
            reason: info.reason,
            action: (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    to={RATE_LIMITS_SETTINGS_URL}
                    onClick={() => {
                        posthog.capture('error_tracking_rate_limit_setup_started', {
                            source: 'recommendation_card',
                            rate_limit_key: rateLimit.key,
                        })
                    }}
                >
                    Set limit
                </LemonButton>
            ),
        }
    })

    return (
        <ListRecommendationCard
            recommendationId={recommendation.id}
            title="Rate limits"
            description="Protect ingestion from runaway exception volume."
            dismissed={dismissed}
            items={items}
            progressLabel="configured"
        />
    )
}
