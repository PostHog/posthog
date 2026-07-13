import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonTabs } from '@posthog/lemon-ui'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { MetricsSetupPrompt } from './components/MetricsSetupPrompt'
import { MetricsSqlEditor } from './components/MetricsSqlEditor'
import { metricsUsageTrackingLogic } from './components/metricsUsageTrackingLogic'
import { MetricsViewer } from './components/MetricsViewer'
import { metricsIngestionLogic } from './metricsIngestionLogic'
import { MetricsSceneActiveTab, metricsSceneLogic } from './metricsSceneLogic'

export const METRICS_LOGIC_KEY = 'metrics'

const TABS: { key: MetricsSceneActiveTab; label: string; 'data-attr': string }[] = [
    { key: 'viewer', label: 'Viewer', 'data-attr': 'metrics-scene-tab-viewer' },
    { key: 'sql', label: 'SQL', 'data-attr': 'metrics-scene-tab-sql' },
]

export const scene: SceneExport = {
    component: MetricsScene,
    logic: metricsSceneLogic,
    productKey: ProductKey.METRICS,
}

export function MetricsScene(): JSX.Element {
    return (
        <SceneContent className="h-[calc(var(--scene-layout-rect-height,_100vh)_-_1rem)]">
            <MetricsSceneContent />
        </SceneContent>
    )
}

const MetricsSceneContent = (): JSX.Element => {
    const { activeTab } = useValues(metricsSceneLogic)
    const { setActiveTab } = useActions(metricsSceneLogic)
    const { teamHasMetricsCheckFailed } = useValues(metricsIngestionLogic)
    // Scene-level so tab switches in both directions are captured; keeps the viewer
    // and samples logics (its connect targets) mounted across tab flips as a side effect.
    useMountedLogic(metricsUsageTrackingLogic)

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
            <LemonTabs<MetricsSceneActiveTab> activeKey={activeTab} onChange={setActiveTab} tabs={TABS} sceneInset />
            <MetricsSetupPrompt>
                <div className="flex flex-col gap-2 py-2 flex-1 min-h-0">
                    {activeTab === 'viewer' && <MetricsViewer />}
                    {activeTab === 'sql' && <MetricsSqlEditor />}
                </div>
            </MetricsSetupPrompt>
        </>
    )
}
