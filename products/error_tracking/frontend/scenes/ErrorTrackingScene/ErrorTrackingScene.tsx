import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { PageHeader } from 'lib/components/PageHeader'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import {
    TabsPrimitive,
    TabsPrimitiveContent,
    TabsPrimitiveList,
    TabsPrimitiveTrigger,
} from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { cn } from 'lib/utils/css-classes'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ErrorTrackingIssueFilteringTool } from '../../components/IssueFilteringTool'
import { ErrorTrackingIssueImpactTool } from '../../components/IssueImpactTool'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { exceptionIngestionLogic } from '../../components/SetupPrompt/exceptionIngestionLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'
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

    return (
        <ErrorTrackingSetupPrompt>
            <Header />

            <ErrorTrackingIssueFilteringTool />
            {hasIssueCorrelation && <ErrorTrackingIssueImpactTool />}

            <SceneContent className="py-2">
                {hasSentExceptionEventLoading || hasSentExceptionEvent ? null : <IngestionStatusCheck />}
                {hasIssueCorrelation ? (
                    <div>
                        <TabsPrimitive
                            value={activeTab}
                            onValueChange={setActiveTab}
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
            </SceneContent>
        </ErrorTrackingSetupPrompt>
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
            <PageHeader
                buttons={
                    <>
                        {isDev ? (
                            <>
                                <LemonButton
                                    onClick={() => {
                                        posthog.captureException(new Error('Kaboom !'))
                                    }}
                                >
                                    Send an exception
                                </LemonButton>
                                <LemonButton onClick={onClick}>Start exception loop</LemonButton>
                            </>
                        ) : null}
                        <LemonButton to="https://posthog.com/docs/error-tracking" type="secondary" targetBlank>
                            Documentation
                        </LemonButton>
                        <LemonButton to={urls.errorTrackingConfiguration()} type="secondary" icon={<IconGear />}>
                            Configure
                        </LemonButton>
                    </>
                }
            />
            <SceneTitleSection
                name="Error tracking"
                description="Track and analyze errors in your website or application to understand and fix issues."
                resourceType={{
                    type: 'error_tracking',
                }}
            />
            <SceneDivider />
        </>
    )
}

const IngestionStatusCheck = (): JSX.Element | null => {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')
    return (
        <LemonBanner type="warning" className={cn(!newSceneLayout && 'mb-4')}>
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
