import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonBanner, LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { MockUxPreview } from '../mock/MockUxPreview'
import { EngineeringAnalyticsAuthors } from './EngineeringAnalyticsAuthors'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { EngineeringAnalyticsPullRequests } from './EngineeringAnalyticsPullRequests'
import {
    EngineeringAnalyticsView,
    VIEW_DESCRIPTIONS,
    engineeringAnalyticsSceneLogic,
} from './engineeringAnalyticsSceneLogic'
import { EngineeringAnalyticsTestHealth } from './EngineeringAnalyticsTestHealth'
import { RepoOverviewScene } from './RepoOverviewScene'

export const scene: SceneExport = {
    component: EngineeringAnalyticsScene,
    logic: engineeringAnalyticsSceneLogic,
}

// Mock-only: the UX-overhaul preview rides a search param instead of a scene key so the throwaway
// reference needs no manifest/route changes. Remove together with ../mock/.
type PreviewableTab = EngineeringAnalyticsView | 'ux-preview'

export function EngineeringAnalyticsScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const { activeView } = useValues(engineeringAnalyticsSceneLogic)
    const logic = engineeringAnalyticsLogic()
    const { anyLoading } = useValues(logic)
    const { refresh } = useActions(logic)
    const { tab: _previewParam, ...linkParams } = searchParams
    const previewActive = _previewParam === 'ux-preview'

    // The general areas of the product. Drill-down pages (workflow, run, PR, author) live below the
    // Overview; the two lens list pages are reachable both here and via the unvalued lens chips.
    const tabs: LemonTab<PreviewableTab>[] = [
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
            key: 'authors',
            label: 'Authors',
            content: <EngineeringAnalyticsAuthors />,
            link: combineUrl(urls.engineeringAnalyticsAuthors(), linkParams).url,
            'data-attr': 'engineering-analytics-authors-tab',
        },
        {
            key: 'test-health',
            label: 'Test health',
            content: <EngineeringAnalyticsTestHealth />,
            link: combineUrl(urls.engineeringAnalyticsTestHealth(), linkParams).url,
            'data-attr': 'engineering-analytics-test-health-tab',
        },
        {
            key: 'ux-preview',
            label: 'UX preview',
            content: <MockUxPreview />,
            link: combineUrl(urls.engineeringAnalytics(), { ...linkParams, tab: 'ux-preview' }).url,
            'data-attr': 'engineering-analytics-ux-preview-tab',
        },
    ]

    return (
        <BindLogic logic={engineeringAnalyticsLogic} props={{}}>
            <SceneContent>
                <SceneTitleSection
                    name="Engineering analytics"
                    description={
                        previewActive
                            ? 'UX overhaul preview — faked data, one lens stack from repo to author.'
                            : VIEW_DESCRIPTIONS[activeView]
                    }
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
                <LemonTabs
                    activeKey={previewActive ? 'ux-preview' : activeView}
                    data-attr="engineering-analytics-tabs"
                    tabs={tabs}
                    sceneInset
                />
            </SceneContent>
        </BindLogic>
    )
}

export default EngineeringAnalyticsScene
