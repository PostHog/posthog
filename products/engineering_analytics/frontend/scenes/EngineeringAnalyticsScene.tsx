import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonButton, LemonTab, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { EngineeringAnalyticsPullRequests } from './EngineeringAnalyticsPullRequests'
import {
    EngineeringAnalyticsTab,
    TAB_DESCRIPTIONS,
    engineeringAnalyticsSceneLogic,
} from './engineeringAnalyticsSceneLogic'
import { EngineeringAnalyticsWorkflows } from './EngineeringAnalyticsWorkflows'

export const scene: SceneExport = {
    component: EngineeringAnalyticsScene,
    logic: engineeringAnalyticsSceneLogic,
}

export function EngineeringAnalyticsScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const { activeTab } = useValues(engineeringAnalyticsSceneLogic)
    const { anyLoading } = useValues(engineeringAnalyticsLogic)
    const { refresh } = useActions(engineeringAnalyticsLogic)

    const tabs: LemonTab<EngineeringAnalyticsTab>[] = [
        {
            key: 'pull-requests',
            label: 'Pull requests',
            content: <EngineeringAnalyticsPullRequests />,
            link: combineUrl(urls.engineeringAnalytics(), searchParams).url,
            'data-attr': 'engineering-analytics-pull-requests-tab',
        },
        {
            key: 'workflows',
            label: 'Workflows',
            content: <EngineeringAnalyticsWorkflows />,
            link: combineUrl(urls.engineeringAnalyticsWorkflows(), searchParams).url,
            'data-attr': 'engineering-analytics-workflows-tab',
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="CI analytics"
                description={TAB_DESCRIPTIONS[activeTab]}
                resourceType={{ type: 'metrics' }}
                actions={
                    <>
                        <LemonTag type="completion">Internal beta</LemonTag>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={refresh}
                            loading={anyLoading}
                            disabledReason={anyLoading ? 'Loading…' : undefined}
                        >
                            Refresh
                        </LemonButton>
                    </>
                }
            />
            <LemonTabs activeKey={activeTab} data-attr="engineering-analytics-tabs" tabs={tabs} sceneInset />
        </SceneContent>
    )
}

export default EngineeringAnalyticsScene
