import { useActions, useValues } from 'kea'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneAgentPanelLogic } from 'scenes/max/sceneAgentPanelLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import {
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { ConversionGoalNoticeState, conversionGoalDraftLogic } from './conversionGoalDraftLogic'
import { conversionRecommendationsLogic } from './conversionRecommendationsLogic'

const NOTICES: Record<ConversionGoalNoticeState, { title: string; description: string }> = {
    idle: {
        title: 'Find conversion goals with AI',
        description: 'Review your events and business definitions in setup to find potential conversion goals.',
    },
    preview: {
        title: 'Previewing a conversion goal',
        description: 'You can continue using the dashboard. Review the result in setup when it is ready.',
    },
    save: {
        title: 'Saving your conversion goal',
        description: 'You can check its progress in setup.',
    },
    verify: {
        title: 'Verifying your conversion goal',
        description: 'Checking that the saved definition matches your draft. Review the result in setup.',
    },
    error: {
        title: 'Your conversion goal needs attention',
        description: 'Your draft is available in setup. Review the details and retry there.',
    },
    review: {
        title: 'A conversion goal draft is ready to review',
        description: 'Review the source and business definition in setup before saving.',
    },
    saved: {
        title: 'Your conversion goal was saved',
        description: 'You can review and manage your conversion goals in setup.',
    },
}

export function ConversionGoalRecommendationsBanner(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { sceneIntegrationEnabled } = useValues(sceneAgentPanelLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { openSetup } = useActions(marketingAnalyticsLogic)
    const { noticeState, busy } = useValues(conversionGoalDraftLogic({ projectId: currentTeamId ?? -1 }))

    const {
        state,
        isAnalyzing,
        error: discoveryError,
    } = useValues(
        conversionRecommendationsLogic({
            projectId: currentTeamId ?? -1,
            userId: user?.uuid,
            enabled: !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_SETUP_AI] && sceneIntegrationEnabled,
        })
    )

    if (
        !featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_SETUP_AI] ||
        !sceneIntegrationEnabled ||
        !currentTeamId ||
        !user
    ) {
        return null
    }

    let notice = NOTICES[noticeState]
    if (!busy && isAnalyzing) {
        notice = {
            title: state?.result_run ? 'Updating conversion recommendations' : 'Finding conversion goals',
            description: state?.result_run
                ? 'Your previous recommendations remain available in setup while the update runs.'
                : 'Analyzing events and actions from the last 30 days. You can keep using the dashboard.',
        }
    } else if (noticeState === 'idle') {
        if (discoveryError || state?.latest_run?.status === 'failed') {
            notice = {
                title: 'Conversion recommendations need attention',
                description: 'Review the error in setup and retry when you are ready.',
            }
        } else if (state?.result_run) {
            notice = state.results.recommendations?.length
                ? {
                      title: 'Conversion recommendations are ready',
                      description: 'Review the proposed sources, business questions, and previews in setup.',
                  }
                : {
                      title: 'No conversion recommendations yet',
                      description: 'Review your events in setup or update after more data arrives.',
                  }
        } else if (!state) {
            notice = {
                title: 'Loading conversion recommendations',
                description: 'Checking whether this project has already been analyzed.',
            }
        }
    }
    return (
        <LemonBanner
            type={
                noticeState === 'error' || discoveryError || state?.latest_run?.status === 'failed'
                    ? 'warning'
                    : noticeState === 'saved'
                      ? 'success'
                      : 'info'
            }
            dismissKey={`marketing-conversion-setup:${user.uuid}:${currentTeamId}`}
            icon={busy || isAnalyzing || (!state && !discoveryError) ? <Spinner /> : undefined}
            action={{
                children: 'Review in setup',
                onClick: () => openSetup(SetupSection.CONVERSION_GOALS, 'dashboard_goal_suggestions'),
                'data-attr': 'marketing-conversion-review-in-setup',
            }}
        >
            <div aria-live="polite">
                <strong>{notice.title}</strong>
                <p className="mb-0 mt-1">{notice.description}</p>
            </div>
        </LemonBanner>
    )
}
