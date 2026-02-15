import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer'
import { LogsSetupPrompt } from 'products/logs/frontend/components/SetupPrompt/SetupPrompt'
import { logsIngestionLogic } from 'products/logs/frontend/components/SetupPrompt/logsIngestionLogic'

import { useOpenLogsSettingsPanel } from './hooks/useOpenLogsSettingsPanel'
import { logsSceneLogic } from './logsSceneLogic'

export const scene: SceneExport = {
    component: LogsScene,
    logic: logsSceneLogic,
    productKey: ProductKey.LOGS,
}

export function LogsScene(): JSX.Element {
    return (
        <SceneContent>
            <LogsSceneContent />
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
                        {hasLogs && (
                            <LemonButton size="small" type="secondary" id="logs-feedback-button">
                                Send feedback
                            </LemonButton>
                        )}
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
                <div className="flex flex-col gap-2 py-2 h-[calc(100vh_-_var(--breadcrumbs-height-compact,_0px)_-_var(--scene-title-section-height,_0px)_-_5px_+_10rem)]">
                    <LogsViewer id={tabId} />
                </div>
            </LogsSetupPrompt>
        </>
    )
}
