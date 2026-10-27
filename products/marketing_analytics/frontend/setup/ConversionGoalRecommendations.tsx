import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonBanner, LemonButton, LemonCard, LemonCollapse } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import type { ConversionRecommendationApi } from '../generated/api.schemas'
import { conversionGoalFormLogic } from './conversionGoalFormLogic'
import { ConversionRecommendationCard } from './ConversionRecommendationCard'
import { conversionRecommendationsLogic } from './conversionRecommendationsLogic'

export function ConversionGoalRecommendations({
    onConfigureGoals,
    onUseSuggestion,
    headerAction,
    hideWhenConfigured = false,
}: {
    onConfigureGoals: () => void
    onUseSuggestion: (recommendation: ConversionRecommendationApi) => void
    headerAction?: ReactNode
    hideWhenConfigured?: boolean
}): JSX.Element | null {
    const { currentTeamId, currentTeamLoading } = useValues(teamLogic)
    const { isSaving } = useValues(conversionGoalFormLogic({ projectId: currentTeamId ?? -1 }))
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
    const {
        state,
        stateLoading,
        isAnalyzing,
        error,
        pendingRecommendations,
        allRecommendationsConfigured,
        allRecommendationsHandled,
        dismissedRecommendationEntries,
        scanCooldownRemaining,
        scanDisabledReason,
    } = useValues(logic)
    const { requestAnalysis, loadRecommendations, dismissRecommendation, restoreRecommendation } = useActions(logic)

    if (
        !enabled ||
        currentTeamId === null ||
        (hideWhenConfigured &&
            allRecommendationsHandled &&
            !stateLoading &&
            !isAnalyzing &&
            !error &&
            state?.latest_run?.status !== 'failed')
    ) {
        return null
    }
    return (
        <LemonCard
            hoverEffect={false}
            className="p-0 mt-4 overflow-hidden"
            data-attr="marketing-conversion-recommendations"
        >
            <div className="p-4 space-y-3">
                <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                        <h3 className="text-base mb-1">
                            {allRecommendationsConfigured ? 'Conversion goals' : 'Suggested conversion goals'}
                        </h3>
                        <p className="mb-0 text-secondary text-sm">
                            {allRecommendationsConfigured
                                ? 'All suggestions from your last successful scan are configured.'
                                : allRecommendationsHandled && dismissedRecommendationEntries.length > 0
                                  ? 'No pending suggestions. You can review and restore dismissed suggestions below.'
                                  : 'Review suggested events and actions before adding a goal.'}
                        </p>
                    </div>
                    {headerAction}
                </div>
                {state?.generation_disabled_reason && (
                    <LemonBanner type="info">{state.generation_disabled_reason}</LemonBanner>
                )}
                {!state && stateLoading && <LemonBanner type="info">Loading conversion recommendations…</LemonBanner>}
                {isAnalyzing && (
                    <LemonBanner type="info">
                        Scanning events and actions from the last {state?.latest_run?.lookback_days} days.{' '}
                        {state?.result_run
                            ? 'Previous suggestions remain available.'
                            : 'You can leave this page while it runs.'}
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
                    <LemonBanner type="warning">
                        {allRecommendationsConfigured
                            ? 'The latest scan failed. Your configured goals are unchanged. Scan again to retry.'
                            : state.result_run
                              ? 'The latest scan failed. Suggestions from your last successful scan are still available. Scan again to retry.'
                              : 'Could not scan events and actions. Scan again to retry.'}
                    </LemonBanner>
                )}
                {state?.result_run && (state.results.recommendations?.length ?? 0) === 0 && (
                    <LemonBanner type="info">
                        No additional goals were found. Review your configured goals or scan again after more data
                        arrives.
                    </LemonBanner>
                )}
                {pendingRecommendations.length > 0 && (
                    <div className="divide-y border-t">
                        {pendingRecommendations.map((recommendation) => (
                            <ConversionRecommendationCard
                                key={recommendation.source_ref}
                                recommendation={recommendation}
                                onUseSuggestion={() => onUseSuggestion(recommendation)}
                                onDismiss={() => dismissRecommendation(recommendation)}
                                disabledReason={
                                    restrictedReason ||
                                    (currentTeamLoading || isSaving
                                        ? 'Wait for the project settings to finish saving.'
                                        : undefined)
                                }
                            />
                        ))}
                    </div>
                )}
                {dismissedRecommendationEntries.length > 0 && (
                    <LemonCollapse
                        embedded
                        size="small"
                        panels={[
                            {
                                key: 'dismissed-suggestions',
                                header: `Dismissed suggestions (${dismissedRecommendationEntries.length})`,
                                content: (
                                    <div className="space-y-2">
                                        <p className="text-secondary text-sm mb-0">
                                            Hidden for you in this browser. Restore a suggestion to show it again if it
                                            is in the latest scan, or allow it in future scans.
                                        </p>
                                        <div className="divide-y">
                                            {dismissedRecommendationEntries.map((recommendation) => (
                                                <div
                                                    key={recommendation.source_ref}
                                                    className="flex flex-wrap items-center justify-between gap-2 py-2"
                                                >
                                                    <div className="min-w-0 flex-1 basis-48">
                                                        <strong className="break-words">{recommendation.name}</strong>
                                                        <p className="text-secondary text-xs mb-0 break-all">
                                                            {recommendation.source_ref}
                                                        </p>
                                                    </div>
                                                    <LemonButton
                                                        size="small"
                                                        type="secondary"
                                                        onClick={() => restoreRecommendation(recommendation.source_ref)}
                                                        data-attr="marketing-conversion-restore-suggestion"
                                                    >
                                                        Restore
                                                    </LemonButton>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                ),
                            },
                        ]}
                    />
                )}
                {(state?.result_run ||
                    state?.latest_run?.status === 'failed' ||
                    !!state?.results.limitations?.length) && (
                    <LemonCollapse
                        embedded
                        size="small"
                        panels={[
                            {
                                key: 'scan-details',
                                header: 'Scan details',
                                content: (
                                    <div className="text-secondary text-sm space-y-2">
                                        {state?.result_run && (
                                            <p className="mb-0">
                                                <span>Analysis period: </span>
                                                <TZLabel time={state.result_run.date_from} timestampStyle="absolute" />
                                                <span> to </span>
                                                <TZLabel time={state.result_run.date_to} timestampStyle="absolute" />
                                                <span>. Applied suggestions are hidden.</span>
                                            </p>
                                        )}
                                        {state?.latest_run?.status === 'failed' && state.latest_run.error && (
                                            <p className="mb-0">{state.latest_run.error}</p>
                                        )}
                                        {!!state?.results.limitations?.length && (
                                            <ul className="pl-5 mb-0">
                                                {state.results.limitations.map((limitation) => (
                                                    <li key={limitation}>{limitation}</li>
                                                ))}
                                            </ul>
                                        )}
                                    </div>
                                ),
                            },
                        ]}
                    />
                )}
            </div>
            <div className="border-t px-4 py-3 flex flex-wrap items-center justify-between gap-2 bg-bg-light">
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onConfigureGoals}
                    data-attr="marketing-conversion-configure-goals"
                >
                    Configure goals
                </LemonButton>
                <div className="flex flex-wrap items-center gap-2">
                    {!isAnalyzing && scanCooldownRemaining > 0 && state?.can_generate && (
                        <span className="text-secondary text-sm">{scanDisabledReason}</span>
                    )}
                    <LemonButton
                        type="secondary"
                        size="small"
                        loading={isAnalyzing || stateLoading}
                        disabledReason={scanDisabledReason}
                        onClick={() => requestAnalysis(true)}
                        data-attr="marketing-conversion-update-recommendations"
                    >
                        {isAnalyzing ? 'Scanning…' : state?.latest_run ? 'Scan again' : 'Scan events'}
                    </LemonButton>
                </div>
            </div>
        </LemonCard>
    )
}
