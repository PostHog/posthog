import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { AddSourceStep } from 'scenes/marketing-analytics/Onboarding/AddSourceStep'
import { marketingOnboardingLogic } from 'scenes/marketing-analytics/Onboarding/marketingOnboardingLogic'
import { teamLogic } from 'scenes/teamLogic'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'
import { nativeSourceDisplayLabel } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { detectedSourcesLogic } from './detectedSourcesLogic'
import { SourceSetupPanel } from './SourceSetupPanel'

export function DetectedSources({ compact = false }: { compact?: boolean }): JSX.Element | null {
    const { visibleSuggestions, setupPlan, setupPlanLoading, sourceScanDisabledReason } = useValues(setupPlanLogic)
    const { rescanSources } = useActions(setupPlanLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { dismissedSourceIds, showIntegrations } = useValues(detectedSourcesLogic({ teamId: currentTeamId ?? 0 }))
    const { dismissSource, setShowIntegrations } = useActions(detectedSourcesLogic({ teamId: currentTeamId ?? 0 }))
    const { allAvailableSourcesWithStatus, nativeSources, hasSyncedMarketingSources, loading } =
        useValues(marketingAnalyticsLogic)
    const { setManualSourceSearch } = useActions(marketingOnboardingLogic)
    const sources = visibleSuggestions.filter(
        (suggestion) =>
            suggestion.kind === 'connect_source' &&
            suggestion.apply?.op === 'open_source_wizard' &&
            !nativeSources.some((source) => source.source_type === suggestion.apply?.kind) &&
            !allAvailableSourcesWithStatus.some((source) => source.source_type === suggestion.apply?.kind) &&
            !dismissedSourceIds.includes(suggestion.id)
    )
    const connections = nativeSources.map((source) => ({
        id: source.id,
        name: nativeSourceDisplayLabel(source.source_type),
        sourceType: source.source_type,
        status: (source.status === 'Running'
            ? 'Syncing'
            : source.status === 'Failed'
              ? 'Needs attention'
              : 'Connected') as 'Connected' | 'Syncing' | 'Needs attention',
        detail:
            source.status === 'Running'
                ? 'Your first import is running. Spend data will appear when it finishes.'
                : source.status === 'Failed'
                  ? 'The import failed. Open setup to check this connection.'
                  : 'Waiting for the first sync to finish.',
    }))
    const openIntegrations = (): void => {
        setManualSourceSearch('')
        setShowIntegrations(true)
    }
    if (!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING]) {
        return hasSyncedMarketingSources ? null : <AddSourceStep hasSources={connections.length > 0} />
    }
    if (showIntegrations) {
        return (
            <AddSourceStep
                hasSources={connections.length > 0 || hasSyncedMarketingSources}
                onBack={() => setShowIntegrations(false)}
            />
        )
    }
    if (hasSyncedMarketingSources && !sources.length) {
        return null
    }
    if (hasSyncedMarketingSources) {
        return (
            <div className="mt-4 flex flex-wrap items-center gap-3">
                <span className="text-secondary text-sm">
                    {sources.length} suggested {sources.length === 1 ? 'connection' : 'connections'}
                </span>
                <LemonButton size="small" onClick={openIntegrations}>
                    Browse integrations
                </LemonButton>
            </div>
        )
    }
    return (
        <SourceSetupPanel
            compact={compact}
            state={
                connections.length
                    ? 'waiting'
                    : setupPlanLoading && !setupPlan
                      ? 'scanning'
                      : !setupPlan && !loading
                        ? 'error'
                        : sources.length
                          ? 'suggestions'
                          : 'empty'
            }
            suggestions={sources}
            connections={connections}
            onRetry={rescanSources}
            rescanLoading={setupPlanLoading}
            rescanDisabledReason={sourceScanDisabledReason}
            onDismiss={dismissSource}
            footer={
                <>
                    <LemonButton
                        type={sources.length || connections.length ? 'secondary' : 'primary'}
                        onClick={openIntegrations}
                        data-attr="marketing-dashboard-connect-source"
                    >
                        Browse integrations
                    </LemonButton>
                </>
            }
        />
    )
}
