import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import {
    TabsPrimitive,
    TabsPrimitiveContent,
    TabsPrimitiveList,
    TabsPrimitiveTrigger,
} from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ErrorTrackingIssueFilteringTool } from '../../components/IssueFilteringTool'
import { issueFiltersLogic } from '../../components/IssueFilters/issueFiltersLogic'
import { ErrorTrackingIssueImpactTool } from '../../components/IssueImpactTool'
import { issueQueryOptionsLogic } from '../../components/IssueQueryOptions/issueQueryOptionsLogic'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { exceptionIngestionLogic } from '../../components/SetupPrompt/exceptionIngestionLogic'
import {
    ERROR_TRACKING_SCENE_LOGIC_KEY,
    ErrorTrackingSceneActiveTab,
    errorTrackingSceneLogic,
} from './errorTrackingSceneLogic'
import { ImpactFilters } from './tabs/impact/ImpactFilters'
import { ImpactList } from './tabs/impact/ImpactList'
import { IssuesFilters } from './tabs/issues/IssuesFilters'
import { IssuesList } from './tabs/issues/IssuesList'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { hasSentExceptionEvent, hasSentExceptionEventLoading } = useValues(exceptionIngestionLogic)
    const { activeTab } = useValues(errorTrackingSceneLogic)
    const { setActiveTab } = useActions(errorTrackingSceneLogic)
    const hasIssueCorrelation = useFeatureFlag('ERROR_TRACKING_ISSUE_CORRELATION')

    useEffect(() => {
        posthog.capture('error_tracking_issues_list_viewed', { active_tab: activeTab })
    }, [])

    return (
        <SceneContent>
            <BindLogic logic={issueFiltersLogic} props={{ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY }}>
                <BindLogic logic={issueQueryOptionsLogic} props={{ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY }}>
                    <ErrorTrackingSetupPrompt>
                        <Header />

                        <ErrorTrackingIssueFilteringTool />
                        {hasIssueCorrelation && <ErrorTrackingIssueImpactTool />}

                        {hasSentExceptionEventLoading || hasSentExceptionEvent ? null : <IngestionStatusCheck />}
                        {hasIssueCorrelation ? (
                            <div>
                                <TabsPrimitive
                                    value={activeTab}
                                    onValueChange={(value) => setActiveTab(value as ErrorTrackingSceneActiveTab)}
                                    className="border rounded bg-surface-primary"
                                >
                                    <TabsPrimitiveList className="border-b">
                                        <TabsPrimitiveTrigger value="issues" className="px-2 py-1 cursor-pointer">
                                            Issues
                                        </TabsPrimitiveTrigger>
                                        <TabsPrimitiveTrigger value="impact" className="px-2 py-1 cursor-pointer">
                                            Impact
                                        </TabsPrimitiveTrigger>
                                    </TabsPrimitiveList>
                                    <TabsPrimitiveContent value="issues" className="p-2">
                                        <IssuesFilters />
                                    </TabsPrimitiveContent>
                                    <TabsPrimitiveContent value="impact" className="p-2">
                                        <ImpactFilters />
                                    </TabsPrimitiveContent>
                                </TabsPrimitive>
                                {activeTab === 'issues' ? <IssuesList /> : <ImpactList />}
                            </div>
                        ) : (
                            <div>
                                <div className="border rounded bg-surface-primary p-2">
                                    <IssuesFilters />
                                </div>
                                <IssuesList />
                            </div>
                        )}
                    </ErrorTrackingSetupPrompt>
                </BindLogic>
            </BindLogic>
        </SceneContent>
    )
}

const Header = (): JSX.Element => {
    const { isDev } = useValues(preflightLogic)

    const onClick = (): void => {
        setInterval(() => {
            throw new Error('Kaboom !')
        }, 100)
    }

    return (
        <>
            <SceneTitleSection
                name={sceneConfigurations[Scene.ErrorTracking].name}
                description={null}
                resourceType={{
                    type: sceneConfigurations[Scene.ErrorTracking].iconType || 'default_icon_type',
                }}
                actions={
                    <>
                        {isDev ? (
                            <>
                                <LemonButton
                                    size="small"
                                    onClick={() => {
                                        posthog.captureException(new Error('Kaboom !'))
                                    }}
                                >
                                    Send an exception
                                </LemonButton>
                                <LemonButton size="small" onClick={onClick}>
                                    Start exception loop
                                </LemonButton>
                            </>
                        ) : null}
                        <LemonButton
                            size="small"
                            to="https://posthog.com/docs/error-tracking"
                            type="secondary"
                            targetBlank
                        >
                            Documentation
                        </LemonButton>
                        <LemonButton
                            size="small"
                            to={urls.errorTrackingConfiguration()}
                            type="secondary"
                            icon={<IconGear />}
                        >
                            Configure
                        </LemonButton>
                    </>
                }
            />
        </>
    )
}

const IngestionStatusCheck = (): JSX.Element | null => {
    return (
        <LemonBanner type="warning">
            <p>
                <strong>No Exception events have been detected!</strong>
            </p>
            <p>
                To use the Error tracking product, please{' '}
                <Link to="https://posthog.com/docs/error-tracking/installation">
                    enable exception capture within the PostHog SDK
                </Link>{' '}
                (otherwise it'll be a little empty!)
            </p>
        </LemonBanner>
    )
}
