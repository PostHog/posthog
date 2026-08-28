import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonBanner, LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { doraLogic } from './doraLogic'
import { EngineeringAnalyticsHealth } from './EngineeringAnalyticsHealth'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { EngineeringAnalyticsPullRequests } from './EngineeringAnalyticsPullRequests'
import {
    EngineeringAnalyticsView,
    VIEW_DESCRIPTIONS,
    engineeringAnalyticsSceneLogic,
} from './engineeringAnalyticsSceneLogic'
import { EngineeringAnalyticsTeams } from './EngineeringAnalyticsTeams'
import { EngineeringAnalyticsTestHealth } from './EngineeringAnalyticsTestHealth'
import { EngineeringAnalyticsWorkflows } from './EngineeringAnalyticsWorkflows'
import { RepoOverviewScene } from './RepoOverviewScene'

export const scene: SceneExport = {
    component: EngineeringAnalyticsScene,
    logic: engineeringAnalyticsSceneLogic,
}

function RefreshButton({ extraLoading = false }: { extraLoading?: boolean }): JSX.Element {
    const logic = engineeringAnalyticsLogic()
    const { anyLoading } = useValues(logic)
    const { refresh } = useActions(logic)
    const loading = anyLoading || extraLoading
    return (
        <LemonButton
            type="secondary"
            size="small"
            onClick={refresh}
            loading={loading}
            disabledReason={loading ? 'Loading…' : undefined}
        >
            Refresh
        </LemonButton>
    )
}

// Rendered only while the Health tab is active, where its content keeps doraLogic mounted —
// subscribing here adds no eager DORA load on the other tabs. The DORA loading state can't
// join anyLoading directly: doraLogic already connects from engineeringAnalyticsLogic, and a
// reverse connect would make the two logics circular.
function HealthRefreshButton(): JSX.Element {
    const { doraLoading } = useValues(doraLogic)
    return <RefreshButton extraLoading={doraLoading} />
}

export function EngineeringAnalyticsScene(): JSX.Element {
    const { searchParams: linkParams } = useValues(router)
    const { activeView } = useValues(engineeringAnalyticsSceneLogic)

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
            key: 'teams',
            label: 'Teams',
            content: <EngineeringAnalyticsTeams />,
            link: combineUrl(urls.engineeringAnalyticsTeams(), linkParams).url,
            'data-attr': 'engineering-analytics-teams-tab',
        },
        {
            key: 'test-health',
            label: 'Test health',
            content: <EngineeringAnalyticsTestHealth />,
            link: combineUrl(urls.engineeringAnalyticsTestHealth(), linkParams).url,
            'data-attr': 'engineering-analytics-test-health-tab',
        },
        {
            key: 'health',
            label: 'Health',
            content: <EngineeringAnalyticsHealth />,
            link: combineUrl(urls.engineeringAnalyticsHealth(), linkParams).url,
            'data-attr': 'engineering-analytics-health-tab',
        },
    ]

    return (
        <BindLogic logic={engineeringAnalyticsLogic} props={{}}>
            <SceneContent className="pb-16">
                <SceneTitleSection
                    name="Engineering analytics"
                    description={VIEW_DESCRIPTIONS[activeView]}
                    resourceType={{ type: 'health' }}
                    actions={activeView === 'health' ? <HealthRefreshButton /> : <RefreshButton />}
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
