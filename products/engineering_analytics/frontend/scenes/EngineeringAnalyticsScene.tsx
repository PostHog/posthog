import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

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

const VIEW_CONTENT: Record<EngineeringAnalyticsView, () => JSX.Element> = {
    hub: RepoOverviewScene,
    'pull-requests': EngineeringAnalyticsPullRequests,
    authors: EngineeringAnalyticsAuthors,
    'test-health': EngineeringAnalyticsTestHealth,
}

export function EngineeringAnalyticsScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const { activeView } = useValues(engineeringAnalyticsSceneLogic)
    const logic = engineeringAnalyticsLogic()
    const { anyLoading } = useValues(logic)
    const { refresh } = useActions(logic)
    // Mock-only: the UX-overhaul preview rides a search param instead of a scene key so the throwaway
    // reference needs no manifest/route changes. Remove together with ../mock/.
    const previewActive = searchParams.tab === 'ux-preview'
    const Content = VIEW_CONTENT[activeView]

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
                {previewActive ? <MockUxPreview /> : <Content />}
            </SceneContent>
        </BindLogic>
    )
}

export default EngineeringAnalyticsScene
