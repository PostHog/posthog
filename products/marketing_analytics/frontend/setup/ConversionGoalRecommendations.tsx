import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { sceneAgentPanelLogic } from 'scenes/max/sceneAgentPanelLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { ConversionGoalDraftCard } from './ConversionGoalDraftCard'
import { conversionGoalDraftLogic } from './conversionGoalDraftLogic'
import { ConversionRecommendationCard } from './ConversionRecommendationCard'
import { conversionRecommendationsLogic } from './conversionRecommendationsLogic'

const REQUEST =
    'Review this project’s events, actions, and existing goals for Marketing analytics. Recommend up to three business-relevant conversion goals for the last 14 days, excluding configured test accounts. Discover this organization’s definitions and distinguish engagement, customers, and revenue. Explain the counting entity, source evidence, and unresolved decisions. Preview supported drafts. Keep unsupported or unverified definitions conditional. Do not create or modify goals, actions, views, or settings.'

export function ConversionGoalRecommendations(): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { sceneIntegrationEnabled } = useValues(sceneAgentPanelLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const logic = conversionGoalDraftLogic({ projectId: currentTeamId ?? -1 })
    const {
        draft,
        draftValidated,
        pendingDraft,
        preview,
        busy,
        error,
        definitionConfirmed,
        saveStatus,
        saveDisabledReason,
    } = useValues(logic)
    const { receiveDraft, reviewPendingDraft, editGoal, confirmDefinition, previewDraft, saveDraft, verifySave } =
        useActions(logic)
    const recommendationsLogic = conversionRecommendationsLogic({
        projectId: currentTeamId ?? -1,
        enabled: sceneIntegrationEnabled,
        userId: user?.uuid,
    })
    const { state, stateLoading, isAnalyzing, error: discoveryError } = useValues(recommendationsLogic)
    const { requestAnalysis, loadRecommendations } = useActions(recommendationsLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const active = sceneIntegrationEnabled && currentTeamId !== null
    if (!active) {
        return null
    }
    return (
        <div className="space-y-4" data-attr="marketing-conversion-recommendations">
            <LemonCard className="space-y-3">
                <h3 className="mb-0">Conversion recommendations</h3>
                <p className="mb-0 text-secondary">
                    Review events and actions against your business goals. PostHog AI explains the evidence, previews
                    supported definitions, and asks about missing information.
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
                        icon={<IconSparkles />}
                        onClick={() => openSidePanel(SidePanelTab.Max, REQUEST)}
                        data-attr="marketing-conversion-ask-ai"
                    >
                        Ask PostHog AI
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
                        : 'Analyzing events and actions from the last 30 days. You can keep using the dashboard.'}
                </LemonBanner>
            )}
            {discoveryError && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry loading',
                        onClick: () => loadRecommendations(),
                        disabledReason: stateLoading ? 'Wait for the current request.' : undefined,
                    }}
                >
                    {discoveryError}
                </LemonBanner>
            )}
            {state?.latest_run?.status === 'failed' && (
                <LemonBanner type="warning">{state.latest_run.error}</LemonBanner>
            )}
            {state?.result_run && (
                <p className="text-secondary mb-0">
                    Analysis period: {state.result_run.date_from.slice(0, 10)} to{' '}
                    {state.result_run.date_to.slice(0, 10)}. Results stay here until you request an update.
                </p>
            )}
            {state?.result_run && (state.results.recommendations?.length ?? 0) === 0 && (
                <LemonBanner type="info">
                    No suitable conversion goals were found in this analysis. Review your events with PostHog AI,
                    configure a goal manually, or update after more data arrives.
                </LemonBanner>
            )}
            {state?.results.recommendations?.map((recommendation) => (
                <ConversionRecommendationCard
                    key={recommendation.source_ref}
                    recommendation={recommendation}
                    disabledReason={
                        busy || saveStatus === 'unknown'
                            ? 'Finish the current request or verify the save first.'
                            : undefined
                    }
                    onReview={() => {
                        if (recommendation.draft) {
                            receiveDraft(recommendation.draft)
                            reviewPendingDraft()
                        }
                    }}
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
            {pendingDraft && (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Review draft',
                        onClick: reviewPendingDraft,
                        disabledReason:
                            busy || saveStatus === 'unknown'
                                ? 'Finish the current request or verify the save first.'
                                : undefined,
                    }}
                >
                    PostHog AI previewed a draft. Load it here to review and adjust it.
                </LemonBanner>
            )}
            {!draftValidated && busy === 'preview' && (
                <LemonBanner type="info">Loading a fresh preview for this project…</LemonBanner>
            )}
            {!draftValidated && error && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry preview',
                        onClick: previewDraft,
                        disabledReason: busy ? 'Wait for the current request.' : undefined,
                    }}
                >
                    {error}
                </LemonBanner>
            )}
            {draft && draftValidated && (
                <ConversionGoalDraftCard
                    draft={draft}
                    preview={preview}
                    busy={busy}
                    error={error}
                    confirmed={definitionConfirmed}
                    saveStatus={saveStatus}
                    saveDisabledReason={saveDisabledReason}
                    restrictionReason={restrictionReason}
                    onChange={editGoal}
                    onConfirm={confirmDefinition}
                    onPreview={previewDraft}
                    onSave={saveDraft}
                    onVerify={verifySave}
                />
            )}
        </div>
    )
}
