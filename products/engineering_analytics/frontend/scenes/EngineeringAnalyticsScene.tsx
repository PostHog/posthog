import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonBanner, LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { EngineeringAnalyticsPullRequests } from './EngineeringAnalyticsPullRequests'
import {
    EngineeringAnalyticsView,
    VIEW_DESCRIPTIONS,
    engineeringAnalyticsSceneLogic,
} from './engineeringAnalyticsSceneLogic'
import { EngineeringAnalyticsTestHealth } from './EngineeringAnalyticsTestHealth'
import { EngineeringAnalyticsWorkflows } from './EngineeringAnalyticsWorkflows'
import { RepoOverviewScene } from './RepoOverviewScene'

export const scene: SceneExport = {
    component: EngineeringAnalyticsScene,
    logic: engineeringAnalyticsSceneLogic,
}

export function EngineeringAnalyticsScene(): JSX.Element {
    const { searchParams: linkParams } = useValues(router)
    const { activeView } = useValues(engineeringAnalyticsSceneLogic)
    const logic = engineeringAnalyticsLogic()
    const { anyLoading } = useValues(logic)
    const { refresh } = useActions(logic)

    // The general areas of the product. Drill-down pages (workflow, run, PR) live below the Overview.
    const tabs: LemonTab<EngineeringAnalyticsView>[] = [
        {
            key: 'hub',
            label: 'Overview',
            content: <RepoOverviewScene />,
            link: combineUrl(urls.engineeringAnalytics(), linkParams).url,
            'data-attr': 'engineering-analytics-overview-tab',
        },
        {
            key: 'pull-requests',
            label: 'Pull requests',
            content: <EngineeringAnalyticsPullRequests />,
            link: combineUrl(urls.engineeringAnalyticsPullRequestList(), linkParams).url,
            'data-attr': 'engineering-analytics-pull-requests-tab',
        },
        {
            key: 'workflows',
            label: 'Workflows',
            content: <EngineeringAnalyticsWorkflows />,
            link: combineUrl(urls.engineeringAnalyticsWorkflows(), linkParams).url,
            'data-attr': 'engineering-analytics-workflows-tab',
        },
        {
            key: 'test-health',
            label: 'Test health',
            content: <EngineeringAnalyticsTestHealth />,
            link: combineUrl(urls.engineeringAnalyticsTestHealth(), linkParams).url,
            'data-attr': 'engineering-analytics-test-health-tab',
        },
    ]

    return (
        <BindLogic logic={engineeringAnalyticsLogic} props={{}}>
            <SceneContent>
                <SceneTitleSection
                    name="Engineering analytics"
                    description={VIEW_DESCRIPTIONS[activeView]}
                    resourceType={{ type: 'health' }}
                    actions={
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={refresh}
                            loading={anyLoading}
                            disabledReason={anyLoading ? 'Loading…' : undefined}
                        >
                            Refresh
                        </LemonButton>
                    }
                />
                <LemonBanner type="info" dismissKey="engineering-analytics-alpha">
                    Engineering analytics is in alpha. Metrics are limited to CI events, and details may change.
                </LemonBanner>
                <LemonTabs activeKey={activeView} data-attr="engineering-analytics-tabs" tabs={tabs} sceneInset />
            </SceneContent>
        </BindLogic>
    )
}

export default EngineeringAnalyticsScene
