import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer'
import { LogsFilterBar } from 'products/logs/frontend/components/LogsViewer/Filters/LogsFilterBar'
import { LogsSetupPrompt } from 'products/logs/frontend/components/SetupPrompt/SetupPrompt'
import { logsIngestionLogic } from 'products/logs/frontend/components/SetupPrompt/logsIngestionLogic'

import { logsSceneLogic } from './logsSceneLogic'

export const scene: SceneExport = {
    component: LogsScene,
    logic: logsSceneLogic,
    settingSectionId: 'environment-logs',
}

export function LogsScene(): JSX.Element {
    return (
        <SceneContent>
            <LogsSetupPrompt>
                <LogsSceneContent />
            </LogsSetupPrompt>
        </SceneContent>
    )
}

const LogsSceneContent = (): JSX.Element => {
    const {
        tabId,
        parsedLogs,
        logsLoading,
        totalLogsMatchingFilters,
        sparklineLoading,
        hasMoreLogsToLoad,
        orderBy,
        sparklineData,
        sparklineBreakdownBy,
    } = useValues(logsSceneLogic)
    const { teamHasLogsCheckFailed } = useValues(logsIngestionLogic)
    const { runQuery, fetchNextLogsPage, setOrderBy, addFilter, setDateRange, setSparklineBreakdownBy } =
        useActions(logsSceneLogic)

    return (
        <>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Logs].name}
                description={sceneConfigurations[Scene.Logs].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Logs].iconType || 'default_icon_type',
                }}
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
            <LemonBanner
                type="warning"
                dismissKey="logs-beta-banner"
                action={{ children: 'Send feedback', id: 'logs-feedback-button' }}
            >
                <p>
                    Logs is in beta and things will change as we figure out what works. Right now you have 7-day
                    retention with ingestion rate limits. Tell us what you need, what's broken, or if you're hitting
                    limits, we want to hear from you.
                </p>
            </LemonBanner>
            <LogsFilterBar />
            <div className="flex flex-col gap-2 py-2 h-[calc(100vh_-_var(--breadcrumbs-height-compact,_0px)_-_var(--scene-title-section-height,_0px)_-_5px_+_10rem)]">
                <LogsViewer
                    tabId={tabId}
                    logs={parsedLogs}
                    loading={logsLoading}
                    totalLogsCount={sparklineLoading ? undefined : totalLogsMatchingFilters}
                    hasMoreLogsToLoad={hasMoreLogsToLoad}
                    orderBy={orderBy}
                    onChangeOrderBy={setOrderBy}
                    onRefresh={runQuery}
                    onLoadMore={fetchNextLogsPage}
                    onAddFilter={addFilter}
                    sparklineData={sparklineData}
                    sparklineLoading={sparklineLoading}
                    onDateRangeChange={setDateRange}
                    sparklineBreakdownBy={sparklineBreakdownBy}
                    onSparklineBreakdownByChange={setSparklineBreakdownBy}
                />
            </div>
        </>
    )
}
