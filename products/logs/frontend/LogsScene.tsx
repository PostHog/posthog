import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { LogsAlertingSection } from 'products/logs/frontend/components/LogsAlerting/LogsAlertingSection'
import { LogsServices } from 'products/logs/frontend/components/LogsServices/LogsServices'
import { LogsSqlEditor } from 'products/logs/frontend/components/LogsSqlEditor/LogsSqlEditor'
import { LogsViewer } from 'products/logs/frontend/components/LogsViewer'
import { LogsViewerModal } from 'products/logs/frontend/components/LogsViewer/LogsViewerModal'
import { logsIngestionLogic } from 'products/logs/frontend/components/SetupPrompt/logsIngestionLogic'
import { LogsSetupPrompt } from 'products/logs/frontend/components/SetupPrompt/SetupPrompt'

import { useOpenLogsSettingsPanel } from './hooks/useOpenLogsSettingsPanel'
import { LogsSceneActiveTab, logsSceneLogic } from './logsSceneLogic'

export const LOGS_LOGIC_KEY = 'logs'

export const scene: SceneExport = {
    component: LogsScene,
    logic: logsSceneLogic,
    productKey: ProductKey.LOGS,
}

export function LogsScene(): JSX.Element {
    const useTabbedView = useFeatureFlag('LOGS_TABBED_VIEW')

    return (
        <SceneContent className="h-[calc(var(--scene-layout-rect-height,_100vh)_-_1rem)]">
            {useTabbedView ? <LogsSceneTabbedContent /> : <LogsSceneContent />}
        </SceneContent>
    )
}

const LogsSceneContent = (): JSX.Element => {
    const { tabId } = useValues(logsSceneLogic)
    const { hasLogs, teamHasLogsCheckFailed } = useValues(logsIngestionLogic)
    const openLogsSettings = useOpenLogsSettingsPanel()

    return (
        <>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Logs].name}
                description={sceneConfigurations[Scene.Logs].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Logs].iconType || 'default_icon_type',
                }}
                actions={
                    <>
                        {hasLogs && <LogsSceneFeedbackButton />}
                        <LemonButton size="small" type="secondary" icon={<IconGear />} onClick={openLogsSettings}>
                            Settings
                        </LemonButton>
                    </>
                }
            />
            {teamHasLogsCheckFailed && (
                <LemonBanner
                    type="info"
                    dismissKey="logs-setup-hint-banner"
                    action={{
                        to: 'https://posthog.com/docs/logs/',
                        targetBlank: true,
                        children: 'Setup guide',
                    }}
                >
                    Unable to verify logs setup. If you haven't configured logging yet, check out our setup guide.
                </LemonBanner>
            )}
            <LogsSetupPrompt>
                <div className="flex flex-col gap-2 py-2 flex-1 min-h-0">
                    <LogsViewer id={tabId} showSavedViewsButton />
                </div>
            </LogsSetupPrompt>
        </>
    )
}

const LogsSceneTabbedContent = (): JSX.Element => {
    const { tabId, activeTab } = useValues(logsSceneLogic)
    const { setActiveTab } = useActions(logsSceneLogic)
    const { hasLogs, teamHasLogsCheckFailed } = useValues(logsIngestionLogic)
    const showServicesView = useFeatureFlag('LOGS_SERVICES_VIEW')
    const showAlerting = useFeatureFlag('LOGS_ALERTING')
    const showSqlView = useFeatureFlag('LOGS_SQL_VIEW')

    const tabs: { key: LogsSceneActiveTab; label: string }[] = [
        { key: 'viewer', label: 'Viewer' },
        ...(showServicesView ? [{ key: 'services' as const, label: 'Services' }] : []),
        ...(showAlerting ? [{ key: 'alerts' as const, label: 'Alerts' }] : []),
        ...(showSqlView ? [{ key: 'sql' as const, label: 'SQL' }] : []),
        { key: 'configuration', label: 'Configuration' },
    ]

    return (
        <>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Logs].name}
                resourceType={{
                    type: sceneConfigurations[Scene.Logs].iconType || 'default_icon_type',
                }}
                actions={<>{hasLogs && <LogsSceneFeedbackButton />}</>}
            />
            {teamHasLogsCheckFailed && (
                <LemonBanner
                    type="info"
                    dismissKey="logs-setup-hint-banner"
                    action={{
                        to: 'https://posthog.com/docs/logs/',
                        targetBlank: true,
                        children: 'Setup guide',
                    }}
                >
                    Unable to verify logs setup. If you haven't configured logging yet, check out our setup guide.
                </LemonBanner>
            )}
            <LemonTabs<LogsSceneActiveTab>
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key)}
                tabs={tabs}
                sceneInset
            />
            {activeTab === 'viewer' && (
                <LogsSetupPrompt>
                    <div className="flex flex-col gap-2 py-2 flex-1 min-h-0">
                        <LogsViewer id={tabId} showSavedViewsButton />
                    </div>
                </LogsSetupPrompt>
            )}
            {activeTab === 'services' && showServicesView && (
                <>
                    <LogsServices />
                    <LogsViewerModal />
                </>
            )}
            {activeTab === 'alerts' && showAlerting && <LogsAlertingSection />}
            {activeTab === 'sql' && showSqlView && <LogsSqlEditor id={tabId} />}
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
