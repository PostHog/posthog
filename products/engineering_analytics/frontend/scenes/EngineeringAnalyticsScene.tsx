import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'

import { ProductNav } from '../components/ProductNav'
import { RepoSceneTitle } from '../components/RepoSceneTitle'
import { engineeringAnalyticsEmptyState } from '../emptyState/engineeringAnalyticsEmptyState'
import { doraLogic } from './doraLogic'
import { EngineeringAnalyticsAuthors } from './EngineeringAnalyticsAuthors'
import { EngineeringAnalyticsDeploys } from './EngineeringAnalyticsDeploys'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { EngineeringAnalyticsPullRequests } from './EngineeringAnalyticsPullRequests'
import {
    EngineeringAnalyticsView,
    viewDescription,
    engineeringAnalyticsSceneLogic,
} from './engineeringAnalyticsSceneLogic'
import { EngineeringAnalyticsTeams } from './EngineeringAnalyticsTeams'
import { EngineeringAnalyticsTests } from './EngineeringAnalyticsTests'
import { EngineeringAnalyticsWorkflows } from './EngineeringAnalyticsWorkflows'
import { RepoOverviewScene } from './RepoOverviewScene'

export const scene: SceneExport = {
    component: EngineeringAnalyticsScene,
    logic: engineeringAnalyticsSceneLogic,
    productKey: ProductKey.ENGINEERING_ANALYTICS,
    emptyState: engineeringAnalyticsEmptyState,
}

function RefreshButton({ extraLoading = false }: { extraLoading?: boolean }): JSX.Element {
    const logic = engineeringAnalyticsLogic()
    const { anyLoading } = useValues(logic)
    const { refresh } = useActions(logic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const loading = anyLoading || extraLoading
    if (todayRailNav) {
        return (
            <Button
                variant="outline"
                onClick={refresh}
                loading={loading}
                disabledReason={loading ? 'Loading…' : undefined}
            >
                Refresh
            </Button>
        )
    }
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

// Rendered only while the Deploys tab is active, where its content keeps doraLogic mounted.
// Subscribing here adds no eager DORA load on the other tabs. The DORA loading state can't
// join anyLoading directly: doraLogic already connects from engineeringAnalyticsLogic, and a
// reverse connect would make the two logics circular.
function DeploysRefreshButton(): JSX.Element {
    const { doraLoading } = useValues(doraLogic)
    return <RefreshButton extraLoading={doraLoading} />
}

// Each tab's own page. Detail pages render beneath their tab through ProductNav too.
const TAB_CONTENT: Record<EngineeringAnalyticsView, () => JSX.Element> = {
    hub: () => <RepoOverviewScene />,
    'pull-requests': () => <EngineeringAnalyticsPullRequests />,
    workflows: () => <EngineeringAnalyticsWorkflows />,
    tests: () => <EngineeringAnalyticsTests />,
    deploys: () => <EngineeringAnalyticsDeploys />,
    teams: () => <EngineeringAnalyticsTeams />,
    authors: () => <EngineeringAnalyticsAuthors />,
}

function EngineeringAnalyticsTabs(): JSX.Element {
    const { activeView } = useValues(engineeringAnalyticsSceneLogic)
    const { scopeRepo, sourceId } = useValues(engineeringAnalyticsLogic)
    return (
        <ProductNav activeTab={activeView} repo={scopeRepo} sourceId={sourceId}>
            {TAB_CONTENT[activeView]()}
        </ProductNav>
    )
}

export function EngineeringAnalyticsScene(): JSX.Element {
    const { activeView } = useValues(engineeringAnalyticsSceneLogic)
    const { scopeRepo } = useValues(engineeringAnalyticsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <BindLogic logic={engineeringAnalyticsLogic} props={{}}>
            <SceneContent className="pb-16">
                <RepoSceneTitle
                    repo={scopeRepo}
                    description={viewDescription(activeView, scopeRepo)}
                    actions={
                        todayRailNav ? (
                            <div className="flex flex-wrap items-center gap-2">
                                {scopeRepo && (
                                    <Button
                                        variant="outline"
                                        render={
                                            <LinkPrimitive to={`https://github.com/${scopeRepo}`} target="_blank" />
                                        }
                                        data-attr="engineering-analytics-view-on-github"
                                    >
                                        View on GitHub
                                    </Button>
                                )}
                                {activeView === 'deploys' ? <DeploysRefreshButton /> : <RefreshButton />}
                            </div>
                        ) : (
                            <>
                                {scopeRepo && (
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        to={`https://github.com/${scopeRepo}`}
                                        targetBlank
                                        data-attr="engineering-analytics-view-on-github"
                                    >
                                        View on GitHub
                                    </LemonButton>
                                )}
                                {activeView === 'deploys' ? <DeploysRefreshButton /> : <RefreshButton />}
                            </>
                        )
                    }
                />
                <LemonBanner type="info" dismissKey="engineering-analytics-alpha">
                    Engineering analytics is in alpha. Metrics are limited to CI events, and details may change.
                </LemonBanner>
                <EngineeringAnalyticsTabs />
            </SceneContent>
        </BindLogic>
    )
}

export default EngineeringAnalyticsScene
