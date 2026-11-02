import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { marketingOnboardingLogic } from 'scenes/marketing-analytics/Onboarding/marketingOnboardingLogic'
import { teamLogic } from 'scenes/teamLogic'
import { MarketingAnalyticsSourceStatusBanner } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsSourceStatusBanner'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'
import {
    nativeSourceConnectionStatus,
    nativeSourceDisplayLabel,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { DashboardSetupPrompt } from '../setup/DashboardSetupPrompt'
import { detectedSourcesLogic } from './detectedSourcesLogic'
import { SourceCatalog } from './SourceCatalog'
import { SourceSetupPanel } from './SourceSetupPanel'

export function DetectedSources({
    compact = false,
    showRescan = true,
    dismissible = false,
}: {
    compact?: boolean
    showRescan?: boolean
    dismissible?: boolean
}): JSX.Element | null {
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
    const connections = nativeSources.map((source) => {
        const connectionStatus = nativeSourceConnectionStatus(source)
        const issue = allAvailableSourcesWithStatus.find((candidate) => candidate.id === source.id)
        const needsAttention = issue && ['Warning', 'Error', 'Failed', 'Paused', 'Cancelled'].includes(issue.status)
        return {
            id: source.id,
            name: source.prefix || `${nativeSourceDisplayLabel(source.source_type)} (${source.id.slice(0, 8)})`,
            sourceType: source.source_type,
            ...connectionStatus,
            ...(needsAttention ? { status: 'Needs attention' as const } : {}),
            detail: issue && issue.status !== 'Completed' ? issue.statusMessage : connectionStatus.detail,
        }
    })
    const openIntegrations = (): void => {
        setManualSourceSearch('')
        setShowIntegrations(true)
    }
    if (!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING]) {
        return null
    }
    if (showIntegrations) {
        return (
            <>
                <MarketingAnalyticsSourceStatusBanner />
                <SourceCatalog
                    hasSources={connections.length > 0 || hasSyncedMarketingSources}
                    onBack={() => setShowIntegrations(false)}
                />
            </>
        )
    }
    const pendingConnections = hasSyncedMarketingSources
        ? connections.filter((connection) => connection.status === 'Needs attention')
        : connections
    if (hasSyncedMarketingSources && !sources.length && !pendingConnections.length) {
        return <MarketingAnalyticsSourceStatusBanner />
    }
    return (
        <>
            <MarketingAnalyticsSourceStatusBanner
                hiddenSourceIds={pendingConnections.map((connection) => connection.id)}
            />
            <DashboardSetupPrompt
                kind="sources"
                dismissible={dismissible && !pendingConnections.length && !!setupPlan && !setupPlanFailed}
            >
                {(dismissButton) => (
                    <SourceSetupPanel
                        headerAction={dismissButton}
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
                        onRetry={showRescan ? rescanSources : undefined}
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
                )}
            </DashboardSetupPrompt>
        </>
    )
}
