import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { LogsAlertingSection } from 'products/logs/frontend/components/LogsAlerting/LogsAlertingSection'
import { LogsServices } from 'products/logs/frontend/components/LogsServices/LogsServices'
import { LogsServicesV2 } from 'products/logs/frontend/components/LogsServices/LogsServicesV2'
import { LogsSqlEditor } from 'products/logs/frontend/components/LogsSqlEditor/LogsSqlEditor'
import { LogsTransformations } from 'products/logs/frontend/components/LogsTransformations/LogsTransformations'
import { LogsViewer } from 'products/logs/frontend/components/LogsViewer'
import { LogsViewerModal } from 'products/logs/frontend/components/LogsViewer/LogsViewerModal'

import { logsEmptyState } from './emptyState/logsEmptyState'
import { LogsAnomalies } from './LogsAnomalies'
import { LOGS_SCENE_VIEWER_ID, LogsSceneActiveTab, logsSceneLogic } from './logsSceneLogic'

export const LOGS_LOGIC_KEY = 'logs'

export const scene: SceneExport = {
    component: LogsScene,
    logic: logsSceneLogic,
    productKey: ProductKey.LOGS,
    emptyState: logsEmptyState,
}

export function LogsScene(): JSX.Element {
    return (
        <SceneContent className="h-[calc(var(--scene-layout-rect-height,_100vh)_-_1rem)]">
            <LogsSceneTabbedContent />
        </SceneContent>
    )
}

const LogsSceneTabbedContent = (): JSX.Element => {
    const { activeTab } = useValues(logsSceneLogic)
    const { setActiveTab } = useActions(logsSceneLogic)
    const { status: logsSetupStatus } = useValues(productSetupStatusLogic({ productKey: ProductKey.LOGS }))
    const showServicesView = useFeatureFlag('LOGS_SERVICES_VIEW')
    const showServicesV2 = useFeatureFlag('LOGS_SERVICES_VIEW_V2')
    const showServices = activeTab === 'services' && showServicesView
    const showTransformations = useFeatureFlag('LOGS_TRANSFORMATIONS')
    const showAnomalies = useFeatureFlag('LOGS_ANOMALIES')

    const tabs: { key: LogsSceneActiveTab; label: string }[] = [
        { key: 'viewer', label: 'Viewer' },
        ...(showServicesView ? [{ key: 'services' as const, label: 'Services' }] : []),
        { key: 'alerts', label: 'Alerts' },
        ...(showAnomalies ? [{ key: 'anomalies' as const, label: 'Anomalies' }] : []),
        { key: 'sql', label: 'SQL' },
        ...(showTransformations ? [{ key: 'transformations' as const, label: 'Transformations' }] : []),
        { key: 'configuration', label: 'Configuration' },
    ]

    return (
        <>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Logs].name}
                resourceType={{
                    type: sceneConfigurations[Scene.Logs].iconType || 'default_icon_type',
                }}
                actions={<>{logsSetupStatus === 'has-data' && <LogsSceneFeedbackButton />}</>}
            />
            <LemonTabs<LogsSceneActiveTab>
                activeKey={activeTab}
                onChange={(key) => {
                    if (key === 'sql' && activeTab !== 'sql') {
                        posthog.capture('logs sql tab opened')
                    }
                    setActiveTab(key)
                }}
                tabs={tabs}
                sceneInset
            />
            {/* Keep the viewer mounted across tab switches (just hidden when inactive) so its loaded
                logs, scroll position, and virtualized-list state survive — switching away and back
                should not replay the initial loading animation. */}
            <div className={cn('flex flex-col flex-1 min-h-0', activeTab !== 'viewer' && 'hidden')}>
                <div className="flex flex-col gap-2 py-2 flex-1 min-h-0">
                    <LogsViewer id={LOGS_SCENE_VIEWER_ID} showSavedViewsButton />
                </div>
            </div>
            {showServices && showServicesV2 && <LogsServicesV2 />}
            {showServices && !showServicesV2 && (
                <>
                    <LogsServices />
                    <LogsViewerModal />
                </>
            )}
            {activeTab === 'alerts' && <LogsAlertingSection />}
            {activeTab === 'anomalies' && showAnomalies && <LogsAnomalies />}
            {activeTab === 'sql' && <LogsSqlEditor id={LOGS_SCENE_VIEWER_ID} />}
            {activeTab === 'transformations' && showTransformations && <LogsTransformations />}
            {activeTab === 'configuration' && (
                <Settings logicKey={LOGS_LOGIC_KEY} sectionId="environment-logs" settingId="logs" handleLocally />
            )}
        </>
    )
}

const LogsSceneFeedbackButton = (): JSX.Element => {
    return (
        <LemonButton
            size="small"
            type="secondary"
            icon={<IconFeedback />}
            onClick={() => posthog.displaySurvey('019a7d95-3810-0000-34dc-404a58075f17')}
        >
            Feedback
        </LemonButton>
    )
}
