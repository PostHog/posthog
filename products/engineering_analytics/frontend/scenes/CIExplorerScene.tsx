import { useActions, useValues } from 'kea'

import { IconPullRequest, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTabs, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { CIExplorerActivity } from '../components/ciExplorer/CIExplorerActivity'
import { CIExplorerOverview } from '../components/ciExplorer/CIExplorerOverview'
import { CIExplorerSummaryCounts } from '../components/ciExplorer/CIExplorerSummaryCounts'
import { EntityHeader } from '../components/EntityHeader'
import { PullRequestStateTag } from '../components/PullRequestStateTag'
import { CIExplorerLogicProps, CIExplorerView, ciExplorerLogic } from './ciExplorerLogic'

export const scene: SceneExport<CIExplorerLogicProps> = {
    component: CIExplorerScene,
    logic: ciExplorerLogic,
    paramsToProps: ({ params: { repoOwner, repoName, number }, searchParams: { source } }) => ({
        repoOwner: decodeURIComponent(repoOwner),
        repoName: decodeURIComponent(repoName),
        number: parseInt(number, 10),
        sourceId: source ?? null,
    }),
}

export function CIExplorerScene(): JSX.Element {
    const {
        lifecycle,
        prRuns,
        prRunsLoading,
        loadFailed,
        view,
        currentView,
        activePush,
        pullRequestUrl,
        locationUrl,
        syncedAt,
        freshnessLoading,
        refreshing,
    } = useValues(ciExplorerLogic)
    const { loadPrRuns, refresh } = useActions(ciExplorerLogic)

    const pullRequest = lifecycle?.pull_request
    const viewUrl = (target: CIExplorerView): string => locationUrl({ view: target, headSha: null, nodeId: null })
    const busy = refreshing || prRunsLoading

    return (
        <SceneContent className="pb-4">
            <SceneTitleSection
                name="CI explorer"
                resourceType={{ type: 'health' }}
                actions={
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={pullRequestUrl}
                        data-attr="ci-explorer-open-pull-request"
                    >
                        Open pull request
                    </LemonButton>
                }
            />

            {pullRequest && (
                <EntityHeader
                    icon={<IconPullRequest />}
                    title={pullRequest.title}
                    slug={
                        <>
                            <PullRequestStateTag state={pullRequest.state} isDraft={pullRequest.is_draft} />
                            <Link to={pullRequestUrl}>
                                {pullRequest.repo.owner}/{pullRequest.repo.name} #{pullRequest.number}
                            </Link>
                        </>
                    }
                    right={view === 'overview' && activePush ? <CIExplorerSummaryCounts /> : undefined}
                />
            )}

            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-primary">
                <LemonTabs
                    activeKey={currentView}
                    // Each tab is a link, so the router makes the change and Back undoes it.
                    onChange={() => {}}
                    tabs={[
                        { key: 'overview', label: 'Overview', link: viewUrl('overview') },
                        { key: 'activity', label: 'Activity', link: viewUrl('activity') },
                    ]}
                    barClassName="mb-0 border-b-0"
                    data-attr="ci-explorer-views"
                />
                <div className="flex items-center gap-2 pb-1 text-xs text-secondary">
                    <Tooltip title="Last sync of the stored CI data. Refresh reloads it and does not start a sync.">
                        <span>
                            {syncedAt ? (
                                <>
                                    Synced <TZLabel time={syncedAt} />
                                </>
                            ) : freshnessLoading ? (
                                'Checking sync time'
                            ) : (
                                'Sync time unknown'
                            )}
                        </span>
                    </Tooltip>
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        icon={<IconRefresh />}
                        onClick={refresh}
                        loading={busy}
                        disabledReason={busy ? 'Loading' : undefined}
                        data-attr="ci-explorer-refresh"
                    >
                        Refresh
                    </LemonButton>
                </div>
            </div>

            {loadFailed ? (
                <CIAnalyticsLoadError
                    onRetry={loadPrRuns}
                    loading={prRunsLoading}
                    title="Couldn't load this pull request's CI runs"
                />
            ) : prRuns === null ? (
                <LemonSkeleton className="h-96 w-full" />
            ) : view === 'activity' ? (
                <CIExplorerActivity />
            ) : (
                <CIExplorerOverview />
            )}
        </SceneContent>
    )
}
