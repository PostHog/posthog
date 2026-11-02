import { MakeLogicType, actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { VALID_NATIVE_MARKETING_SOURCES } from '~/queries/schema/schema-general'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'

type DetectedSourcesProps = { teamId: number }

function loadSetupPlanIfEnabled(teamId: number): void {
    if (
        featureFlagLogic.values.featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING] &&
        teamId &&
        !setupPlanLogic.values.setupPlan &&
        !setupPlanLogic.values.setupPlanLoading
    ) {
        setupPlanLogic.actions.loadSetupPlan()
    }
}

export const detectedSourcesLogic = kea<
    MakeLogicType<
        { notificationDismissed: boolean; dismissedSourceIds: string[]; showIntegrations: boolean },
        {
            setShowIntegrations: (show: boolean) => { show: boolean }
            dismiss: () => { value: true }
            expand: () => { value: true }
            dismissSource: (id: string) => { id: string }
            clearLegacyDismissals: () => { value: true }
        },
        DetectedSourcesProps
    >
>([
    props({} as DetectedSourcesProps),
    key((props) => props.teamId),
    path((key) => ['products', 'marketingAnalytics', 'detectedSources', key]),
    actions({
        setShowIntegrations: (show: boolean) => ({ show }),
        dismiss: true,
        expand: true,
        dismissSource: (id: string) => ({ id }),
        clearLegacyDismissals: true,
    }),
    reducers(({ props }) => ({
        showIntegrations: [false, { setShowIntegrations: (_, { show }) => show }],
        dismissedSourceIds: [
            [] as string[],
            { persist: true, prefix: `${props.teamId}__` },
            { clearLegacyDismissals: () => [] },
        ],
        notificationDismissed: [
            false,
            { persist: true, prefix: `${props.teamId}__` },
            { dismiss: () => true, expand: () => false },
        ],
    })),
    listeners(({ props }) => ({
        dismissSource: ({ id }) => setupPlanLogic.actions.dismissSuggestion(id),
        [setupPlanLogic.actionTypes.loadSetupPlanSuccess]: () => {
            const logic = detectedSourcesLogic({ teamId: props.teamId })
            for (const id of logic.values.dismissedSourceIds) {
                setupPlanLogic.actions.dismissSuggestion(id)
            }
            logic.actions.clearLegacyDismissals()
        },
        // The app can render on the flag timeout, so the onboarding flag may arrive after mount.
        [featureFlagLogic.actionTypes.setFeatureFlags]: () => loadSetupPlanIfEnabled(props.teamId),
    })),
    afterMount(({ props, cache }) => {
        loadSetupPlanIfEnabled(props.teamId)
        cache.disposables.add(() => {
            const refreshSources = (): void => {
                if (!marketingAnalyticsLogic.values.loading) {
                    marketingAnalyticsLogic.actions.loadSources()
                }
            }
            window.addEventListener('focus', refreshSources)
            let failures = 0
            let retryAt = 0
            const interval = window.setInterval(() => {
                const { sourcesLoadError, dataWarehouseSources } = sourcesDataLogic.values
                if (sourcesLoadError) {
                    if (Date.now() >= retryAt) {
                        refreshSources()
                        failures += 1
                        retryAt = Date.now() + Math.min(30_000 * 2 ** failures, 300_000)
                    }
                    return
                }
                failures = 0
                retryAt = 0
                const searchEnabled =
                    featureFlagLogic.values.featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS]
                if (
                    dataWarehouseSources?.results.some(
                        (source) =>
                            (VALID_NATIVE_MARKETING_SOURCES.includes(
                                source.source_type as (typeof VALID_NATIVE_MARKETING_SOURCES)[number]
                            ) ||
                                (source.source_type === 'GoogleSearchConsole' && searchEnabled)) &&
                            (source.status === 'Running' ||
                                source.schemas.some((schema) => schema.should_sync && schema.status === 'Running'))
                    )
                ) {
                    refreshSources()
                }
            }, 30000)
            return () => {
                window.removeEventListener('focus', refreshSources)
                window.clearInterval(interval)
            }
        }, 'source-health')
    }),
])
