import { useActions, useAsyncActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { RecommendationCard } from './RecommendationCard'
import { recommendationsTabLogic } from './recommendationsTabLogic'
import type { ExceptionAutocaptureRecommendation } from './types'

export function ExceptionAutocaptureRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: ExceptionAutocaptureRecommendation
    dismissed?: boolean
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { addProductIntent } = useActions(teamLogic)
    const { updateCurrentTeam } = useAsyncActions(teamLogic)
    const { reportAutocaptureExceptionsToggled } = useActions(eventUsageLogic)
    const { enableInProgressId } = useValues(recommendationsTabLogic)
    const { refreshRecommendation, setEnableInProgress } = useActions(recommendationsTabLogic)

    const enabled = recommendation.meta.enabled
    const isLoading = enableInProgressId === recommendation.id

    const handleEnable = async (): Promise<void> => {
        if (!currentTeam) {
            return
        }
        posthog.capture('error_tracking_exception_autocapture_enabled_from_recommendation')
        addProductIntent({
            product_type: ProductKey.ERROR_TRACKING,
            intent_context: ProductIntentContext.ERROR_TRACKING_EXCEPTION_AUTOCAPTURE_ENABLED,
        })
        setEnableInProgress(recommendation.id)
        try {
            await updateCurrentTeam({ autocapture_exceptions_opt_in: true })
            reportAutocaptureExceptionsToggled(true)
            refreshRecommendation(recommendation.id)
        } finally {
            setEnableInProgress(null)
        }
    }

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
                <LemonButton size="small" type="secondary" onClick={handleEnable} loading={isLoading}>
                    Turn on autocapture
                </LemonButton>
            )}
        </RecommendationCard>
    )
}
