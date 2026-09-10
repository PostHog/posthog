import { useActions, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner, LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFeedback } from 'lib/lemon-ui/icons'
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
import { MetricsSqlEditor } from './components/MetricsSqlEditor'
import { metricsUsageTrackingLogic } from './components/metricsUsageTrackingLogic'
import { MetricsViewer } from './components/MetricsViewer'
import { metricsEmptyState } from './emptyState/metricsEmptyState'
import { metricsFeaturePreviewGate } from './featurePreviewGate'
import { DEFAULT_ACTIVE_TAB, MetricsSceneActiveTab, metricsSceneLogic } from './metricsSceneLogic'

export const METRICS_LOGIC_KEY = 'metrics'

const METRICS_FEEDBACK_SURVEY_ID = '01a07c35-6be3-0000-16b3-4cd66a6873f3'

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
    emptyState: metricsEmptyState,
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
    // Fundamentals checks the viewer's own reductions against the raw samples, so it is
    // built for the people who work on the viewer rather than for the teams on the alpha.
    const fundamentalsEnabled = useFeatureFlag('METRICS_FUNDAMENTALS')
    const visibleTabs = fundamentalsEnabled ? TABS : TABS.filter((tab) => tab.key !== 'fundamentals')
    // A guessed ?activeTab=fundamentals must not render the tab either, so fall back to the
    // default tab instead of leaving the scene with no visible content.
    const effectiveTab = activeTab === 'fundamentals' && !fundamentalsEnabled ? DEFAULT_ACTIVE_TAB : activeTab
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

    const onFeedbackClick = (): void => {
        posthog.displaySurvey(METRICS_FEEDBACK_SURVEY_ID)
    }

    return (
        <>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Metrics].name}
                description={sceneConfigurations[Scene.Metrics].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Metrics].iconType || 'default_icon_type',
                }}
                actions={
                    <LemonButton size="small" type="secondary" icon={<IconFeedback />} onClick={onFeedbackClick}>
                        Feedback
                    </LemonButton>
                }
            />
            <LemonBanner
                type="warning"
                dismissKey="metrics-alpha-notice"
                action={{
                    icon: <IconFeedback />,
                    children: 'Share feedback',
                    onClick: onFeedbackClick,
                }}
            >
                Metrics is in alpha. Please share feedback on how to improve the product.
            </LemonBanner>
            <LemonTabs<MetricsSceneActiveTab>
                activeKey={effectiveTab}
                onChange={(tab) => {
                    if (!tabDisabledReasons[tab]) {
                        setActiveTab(tab)
                    }
                }}
                tabs={visibleTabs.map((tab) => ({
                    ...tab,
                    disabledReason: tabDisabledReasons[tab.key] ?? undefined,
                }))}
                sceneInset
            />
            <div className="flex flex-col gap-2 py-2 flex-1 min-h-0">
                {effectiveTab === 'overview' && <MetricsOverview />}
                {effectiveTab === 'viewer' && <MetricsViewer />}
                {effectiveTab === 'sql' && <MetricsSqlEditor />}
                {effectiveTab === 'fundamentals' && <MetricsFundamentals />}
            </div>
        </>
    )
}
