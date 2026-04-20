import { useActions, useValues } from 'kea'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { exceptionAutocaptureRecommendationLogic } from './exceptionAutocaptureRecommendationLogic'
import { RecommendationCard } from './RecommendationCard'
import type { ExceptionAutocaptureRecommendation } from './types'

export function ExceptionAutocaptureRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: ExceptionAutocaptureRecommendation
    dismissed?: boolean
}): JSX.Element {
    const { enableInProgress } = useValues(exceptionAutocaptureRecommendationLogic)
    const { enable } = useActions(exceptionAutocaptureRecommendationLogic)

    const enabled = recommendation.meta.enabled

    return (
        <RecommendationCard
            recommendationId={recommendation.id}
            nextRefreshAt={recommendation.next_refresh_at}
            title="Exception autocapture"
            description={
                <>
                    Let the web SDK catch uncaught errors and unhandled promise rejections automatically — no code
                    changes needed. See{' '}
                    <Link to={urls.settings('environment-error-tracking', 'error-tracking-exception-autocapture')}>
                        exception autocapture settings
                    </Link>
                    .
                </>
            }
            dismissed={dismissed}
            progress={enabled ? { current: 1, total: 1, label: 'enabled' } : undefined}
        >
            {!enabled && (
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => enable(recommendation.id)}
                    loading={enableInProgress}
                >
                    Turn on autocapture
                </LemonButton>
            )}
        </RecommendationCard>
    )
}
