import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonTabs } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { metricNamePickerLogic } from './components/metricNamePickerLogic'
import { MetricsFundamentals } from './components/MetricsFundamentals'
import { MetricsOverview } from './components/MetricsOverview'
import { MetricsSetupPrompt } from './components/MetricsSetupPrompt'
import { MetricsSqlEditor } from './components/MetricsSqlEditor'
import { metricsUsageTrackingLogic } from './components/metricsUsageTrackingLogic'
import { MetricsViewer } from './components/MetricsViewer'
import { metricsFeaturePreviewGate } from './featurePreviewGate'
import { metricsIngestionLogic } from './metricsIngestionLogic'
import { MetricsSceneActiveTab, metricsSceneLogic } from './metricsSceneLogic'

export const METRICS_LOGIC_KEY = 'metrics'

const TABS: { key: MetricsSceneActiveTab; label: string; 'data-attr': string }[] = [
    { key: 'overview', label: 'Overview', 'data-attr': 'metrics-scene-tab-overview' },
    { key: 'viewer', label: 'Viewer', 'data-attr': 'metrics-scene-tab-viewer' },
    { key: 'sql', label: 'SQL', 'data-attr': 'metrics-scene-tab-sql' },
    { key: 'fundamentals', label: 'Fundamentals', 'data-attr': 'metrics-scene-tab-fundamentals' },
]

export const scene: SceneExport = {
    component: MetricsScene,
    logic: metricsSceneLogic,
    productKey: ProductKey.METRICS,
}

export function MetricsScene(): JSX.Element {
    return (
        <FeaturePreviewSceneGate config={metricsFeaturePreviewGate}>
            <SceneContent className="h-[calc(var(--scene-layout-rect-height,_100vh)_-_1rem)]">
                <MetricsSceneContent />
            </SceneContent>
        </FeaturePreviewSceneGate>
    )
}

const MetricsSceneContent = (): JSX.Element => {
    const { activeTab } = useValues(metricsSceneLogic)
    const { setActiveTab } = useActions(metricsSceneLogic)
    const { teamHasMetricsCheckFailed } = useValues(metricsIngestionLogic)
    const metricsViewerDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Metrics,
        AccessControlLevel.Viewer
    )
    const metricsSqlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.WarehouseObjects,
        AccessControlLevel.Viewer
    )
    const tabDisabledReasons: Record<MetricsSceneActiveTab, string | null> = {
        overview: metricsViewerDisabledReason,
        viewer: metricsViewerDisabledReason,
        sql: metricsSqlDisabledReason,
        fundamentals: metricsViewerDisabledReason,
    }
    // Scene-level so tab switches in both directions are captured; keeps the viewer
    // and samples logics (its connect targets) mounted across tab flips as a side effect.
    useMountedLogic(metricsUsageTrackingLogic)
    // Prime the metric-name list here rather than inside MetricsViewer, so the fetch
    // races the has_metrics check instead of waiting on the setup prompt to resolve.
    useMountedLogic(metricNamePickerLogic)

    return (
        <>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Metrics].name}
                description={sceneConfigurations[Scene.Metrics].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Metrics].iconType || 'default_icon_type',
                }}
            />
            {teamHasMetricsCheckFailed && (
                <LemonBanner
                    type="info"
                    dismissKey="metrics-setup-hint-banner"
                    action={{
                        to: 'https://posthog.com/docs/metrics',
                        targetBlank: true,
                        children: 'Setup guide',
                    }}
                >
                    Unable to verify metrics setup. If you haven't configured metrics yet, check out our setup guide.
                </LemonBanner>
            )}
            <LemonTabs<MetricsSceneActiveTab>
                activeKey={activeTab}
                onChange={(tab) => {
                    if (!tabDisabledReasons[tab]) {
                        setActiveTab(tab)
                    }
                }}
                tabs={TABS.map((tab) => ({
                    ...tab,
                    disabledReason: tabDisabledReasons[tab.key] ?? undefined,
                }))}
                sceneInset
            />
            <MetricsSetupPrompt>
                <div className="flex flex-col gap-2 py-2 flex-1 min-h-0">
                    {activeTab === 'overview' && <MetricsOverview />}
                    {activeTab === 'viewer' && <MetricsViewer />}
                    {activeTab === 'sql' && <MetricsSqlEditor />}
                    {activeTab === 'fundamentals' && <MetricsFundamentals />}
                </div>
            </MetricsSetupPrompt>
        </>
    )
}
