import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { marketingOnboardingLogic } from 'scenes/marketing-analytics/Onboarding/marketingOnboardingLogic'
import { teamLogic } from 'scenes/teamLogic'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'
import {
    nativeSourceConnectionStatus,
    nativeSourceDisplayLabel,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { detectedSourcesLogic } from './detectedSourcesLogic'
import { SourceCatalog } from './SourceCatalog'
import { SourceSetupPanel } from './SourceSetupPanel'

export function DetectedSources({ compact = false }: { compact?: boolean }): JSX.Element | null {
    const {
        visibleSuggestions,
        dismissedSuggestions,
        setupPlan,
        setupPlanLoading,
        setupPlanFailed,
        sourceScanDisabledReason,
    } = useValues(setupPlanLogic)
    const { rescanSources, restoreAllDismissed } = useActions(setupPlanLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { showIntegrations } = useValues(detectedSourcesLogic({ teamId: currentTeamId ?? 0 }))
    const { dismissSource, setShowIntegrations } = useActions(detectedSourcesLogic({ teamId: currentTeamId ?? 0 }))
    const { allAvailableSourcesWithStatus, nativeSources, hasSyncedMarketingSources } =
        useValues(marketingAnalyticsLogic)
    const { setManualSourceSearch } = useActions(marketingOnboardingLogic)
    const sources = visibleSuggestions.filter(
        (suggestion) =>
            suggestion.kind === 'connect_source' &&
            suggestion.apply?.op === 'open_source_wizard' &&
            !nativeSources.some((source) => source.source_type === suggestion.apply?.kind) &&
            !allAvailableSourcesWithStatus.some((source) => source.source_type === suggestion.apply?.kind)
    )
    const connections = nativeSources.map((source) => ({
        id: source.id,
        name: nativeSourceDisplayLabel(source.source_type),
        sourceType: source.source_type,
        ...nativeSourceConnectionStatus(source),
    }))
    const openIntegrations = (): void => {
        setManualSourceSearch('')
        setShowIntegrations(true)
    }
    if (!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING]) {
        return null
    }
    if (showIntegrations) {
        return (
            <SourceCatalog
                hasSources={connections.length > 0 || hasSyncedMarketingSources}
                onBack={() => setShowIntegrations(false)}
            />
        )
    }
    const pendingConnections = hasSyncedMarketingSources
        ? connections.filter((connection) => connection.status === 'Needs attention')
        : connections
    if (hasSyncedMarketingSources && !sources.length && !pendingConnections.length) {
        return null
    }
    return (
        <SourceSetupPanel
            compact={compact || hasSyncedMarketingSources}
            state={
                pendingConnections.length
                    ? 'waiting'
                    : !setupPlan
                      ? setupPlanFailed
                          ? 'error'
                          : 'scanning'
                      : sources.length
                        ? 'suggestions'
                        : dismissedSuggestions.some((suggestion) => suggestion.kind === 'connect_source')
                          ? 'dismissed'
                          : 'empty'
            }
            suggestions={sources}
            connections={pendingConnections}
            onRetry={rescanSources}
            rescanLoading={setupPlanLoading}
            rescanDisabledReason={sourceScanDisabledReason}
            onDismiss={dismissSource}
            onRestore={restoreAllDismissed}
            footer={
                <LemonButton
                    type={sources.length || connections.length ? 'secondary' : 'primary'}
                    onClick={openIntegrations}
                    data-attr="marketing-dashboard-connect-source"
                >
                    Browse integrations
                </LemonButton>
            }
        />
    )
}
