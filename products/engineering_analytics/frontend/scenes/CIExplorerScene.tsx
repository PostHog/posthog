import { useActions, useValues } from 'kea'

import { IconPullRequest } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSelect, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { CIExplorerCanvas } from '../components/ciExplorer/CIExplorerCanvas'
import { CIExplorerShare } from '../components/ciExplorer/CIExplorerShare'
import { CIExplorerTrail } from '../components/ciExplorer/CIExplorerTrail'
import { EntityHeader } from '../components/EntityHeader'
import { PullRequestStateTag } from '../components/PullRequestStateTag'
import { withCurrentScope } from '../lib/scope'
import { CIExplorerLogicProps, ciExplorerLogic } from './ciExplorerLogic'

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

// More pushes than this no longer fit a row of buttons at a narrow scene width.
const MAX_PUSH_BUTTONS = 5

export function CIExplorerScene(): JSX.Element {
    const { lifecycle, prRuns, prRunsLoading, loadFailed, pushes, activePush, repoOwner, repoName, sourceId } =
        useValues(ciExplorerLogic)
    const { loadPrRuns, selectPush } = useActions(ciExplorerLogic)

    const pullRequest = lifecycle?.pull_request
    const pullRequestUrl = pullRequest
        ? withCurrentScope(urls.engineeringAnalyticsPullRequest(repoOwner, repoName, pullRequest.number), sourceId)
        : null
    const pushOptions = pushes.map((push, index) => ({
        value: push.headSha,
        label: index === 0 ? `${push.headSha.slice(0, 7)} (latest)` : push.headSha.slice(0, 7),
    }))

    return (
        <SceneContent className="pb-4">
            <SceneTitleSection
                name="CI explorer"
                resourceType={{ type: 'health' }}
                actions={
                    pullRequestUrl ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={pullRequestUrl}
                            data-attr="ci-explorer-open-pull-request"
                        >
                            Open pull request
                        </LemonButton>
                    ) : undefined
                }
            />

            {pullRequest && pullRequestUrl && (
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
                    right={
                        activePush && pushOptions.length > 1 ? (
                            pushOptions.length <= MAX_PUSH_BUTTONS ? (
                                <LemonSegmentedButton
                                    size="small"
                                    value={activePush.headSha}
                                    onChange={selectPush}
                                    options={pushOptions}
                                    data-attr="ci-explorer-push"
                                />
                            ) : (
                                <LemonSelect
                                    size="small"
                                    value={activePush.headSha}
                                    onChange={selectPush}
                                    options={pushOptions}
                                    data-attr="ci-explorer-push"
                                />
                            )
                        ) : undefined
                    }
                />
            )}

            {loadFailed ? (
                <CIAnalyticsLoadError
                    onRetry={loadPrRuns}
                    loading={prRunsLoading}
                    title="Couldn't load this pull request's CI runs"
                />
            ) : prRuns === null ? (
                <LemonSkeleton className="h-96 w-full" />
            ) : !activePush ? (
                <div className="py-16 text-center text-sm text-secondary">
                    No CI runs are synced for this pull request yet. Runs appear here after the next sync.
                </div>
            ) : (
                <>
                    <CIExplorerTrail />
                    <CIExplorerShare />
                    {/* The canvas takes the height the header leaves, and no less than a readable minimum. */}
                    <div className="h-[calc(100vh-22rem)] min-h-96 overflow-hidden rounded-lg border border-primary">
                        <CIExplorerCanvas />
                    </div>
                </>
            )}
        </SceneContent>
    )
}
