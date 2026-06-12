import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonBanner, LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
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
import { EngineeringAnalyticsTestHealth } from './EngineeringAnalyticsTestHealth'
import { EngineeringAnalyticsWorkflows } from './EngineeringAnalyticsWorkflows'

export const scene: SceneExport = {
    component: EngineeringAnalyticsScene,
    logic: engineeringAnalyticsSceneLogic,
}

export function EngineeringAnalyticsScene({ tabId }: { tabId?: string }): JSX.Element {
    const { searchParams } = useValues(router)
    const { activeTab } = useValues(engineeringAnalyticsSceneLogic)
    const logic = engineeringAnalyticsLogic({ tabId })
    // Keep this tab's filters and data alive across tab switches (React unmounts inactive tabs).
    useAttachedLogic(logic, tabId ? engineeringAnalyticsSceneLogic({ tabId }) : undefined)
    const { anyLoading } = useValues(logic)
    const { refresh } = useActions(logic)

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
        {
            key: 'test-health',
            label: 'Test health',
            content: <EngineeringAnalyticsTestHealth />,
            link: combineUrl(urls.engineeringAnalyticsTestHealth(), searchParams).url,
            'data-attr': 'engineering-analytics-test-health-tab',
        },
    ]

    return (
        <BindLogic logic={engineeringAnalyticsLogic} props={{ tabId }}>
            <SceneContent>
                <SceneTitleSection
                    name="CI analytics"
                    description={TAB_DESCRIPTIONS[activeTab]}
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
                    CI analytics is in alpha — metrics are limited to CI events, and details may change.
                </LemonBanner>
                <LemonTabs activeKey={activeTab} data-attr="engineering-analytics-tabs" tabs={tabs} sceneInset />
            </SceneContent>
        </BindLogic>
    )
}

export default EngineeringAnalyticsScene
