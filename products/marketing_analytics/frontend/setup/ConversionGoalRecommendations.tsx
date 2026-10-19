import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCard } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import type { ConversionRecommendationApi } from '../generated/api.schemas'
import { ConversionRecommendationCard } from './ConversionRecommendationCard'
import { conversionRecommendationsLogic } from './conversionRecommendationsLogic'

export function ConversionGoalRecommendations({
    onConfigureGoals,
    onUseSuggestion,
}: {
    onConfigureGoals: () => void
    onUseSuggestion: (recommendation: ConversionRecommendationApi) => void
}): JSX.Element | null {
    const { currentTeamId, currentTeamLoading } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const enabled = !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_SETUP_AI]
    const logic = conversionRecommendationsLogic({
        projectId: currentTeamId ?? -1,
        enabled,
        userId: user?.uuid,
    })
    const { state, stateLoading, isAnalyzing, error } = useValues(logic)
    const { requestAnalysis, loadRecommendations } = useActions(logic)

    if (!enabled || currentTeamId === null) {
        return null
    }
    return (
        <div className="space-y-4" data-attr="marketing-conversion-recommendations">
            <LemonCard className="space-y-3">
                <h3 className="mb-0">Conversion recommendations</h3>
                <p className="mb-0 text-secondary">
                    Find events and actions that could measure business outcomes. Review the evidence and business
                    questions before configuring a goal.
                </p>
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        type="primary"
                        loading={isAnalyzing || stateLoading}
                        disabledReason={
                            !state?.can_generate
                                ? (state?.generation_disabled_reason ??
                                  'Project admin access is required to update recommendations.')
                                : undefined
                        }
                        onClick={() => requestAnalysis(true)}
                        data-attr="marketing-conversion-update-recommendations"
                    >
                        Update recommendations
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        onClick={onConfigureGoals}
                        data-attr="marketing-conversion-configure-goals"
                    >
                        Configure goals
                    </LemonButton>
                </div>
            </LemonCard>
            {state?.generation_disabled_reason && (
                <LemonBanner type="info">{state.generation_disabled_reason}</LemonBanner>
            )}
            {!state && stateLoading && <LemonBanner type="info">Loading conversion recommendations…</LemonBanner>}
            {isAnalyzing && (
                <LemonBanner type="info">
                    {state?.result_run
                        ? 'Updating recommendations from the last 14 days. Your previous results remain available below.'
                        : 'Analyzing events and actions from the last 30 days. You can leave Setup while this runs.'}
                </LemonBanner>
            )}
            {error && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry loading',
                        onClick: () => loadRecommendations(),
                        disabledReason: stateLoading ? 'Wait for the current request.' : undefined,
                    }}
                >
                    {error}
                </LemonBanner>
            )}
            {state?.latest_run?.status === 'failed' && (
                <LemonBanner type="warning">{state.latest_run.error}</LemonBanner>
            )}
            {state?.result_run && (
                <p className="text-secondary mb-0">
                    <span>Analysis period: </span>
                    <TZLabel time={state.result_run.date_from} timestampStyle="absolute" />
                    <span> to </span>
                    <TZLabel time={state.result_run.date_to} timestampStyle="absolute" />
                    <span>. Results stay here until you request an update.</span>
                </p>
            )}
            {state?.result_run && (state.results.recommendations?.length ?? 0) === 0 && (
                <LemonBanner type="info">
                    No suitable conversion goals were found in this analysis. Configure a goal manually, or update
                    recommendations after more data arrives.
                </LemonBanner>
            )}
            {state?.results.recommendations?.map((recommendation) => (
                <ConversionRecommendationCard
                    key={recommendation.source_ref}
                    recommendation={recommendation}
                    onUseSuggestion={() => onUseSuggestion(recommendation)}
                    disabledReason={
                        restrictedReason ||
                        (currentTeamLoading ? 'Wait for the project settings to finish saving.' : undefined)
                    }
                />
            ))}
            {!!state?.results.limitations?.length && (
                <details>
                    <summary>Discovery limits</summary>
                    <ul className="pl-5">
                        {state.results.limitations.map((limitation) => (
                            <li key={limitation}>{limitation}</li>
                        ))}
                    </ul>
                </details>
            )}
        </div>
    )
}
