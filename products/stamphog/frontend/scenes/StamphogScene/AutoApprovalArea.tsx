import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { PANE_LEFT, PANE_ROW } from 'lib/components/RepositoryList/paneClasses'
import { RepositoryColumnHeaders } from 'lib/components/RepositoryList/RepositoryColumnHeaders'
import { RepositoryListFilters } from 'lib/components/RepositoryList/RepositoryListFilters'
import { RepositoryPageControls } from 'lib/components/RepositoryList/RepositoryPageControls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { type CodeReviewApprovalRepositoryApi } from '../../generated/api.schemas'
import { DigestHistoryModal } from '../StamphogDigestsScene/DigestHistoryModal'
import { ApproveCell } from './ApproveCell'
import { AutoApprovalConnectionCard } from './AutoApprovalConnectionCard'
import { DigestCell } from './DigestCell'
import { NotAddedRepositoriesRow } from './NotAddedRepositoriesRow'
import { managerDisabledReason } from './repoAccess'
import { ReviewerRequestsCell } from './ReviewerRequestsCell'
import { REPOS_PAGE_SIZE, RepoView, stamphogSceneLogic } from './stamphogSceneLogic'
import { SyncedBanner } from './SyncedBanner'

const VIEW_OPTIONS: { value: RepoView; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'approving', label: 'Approving' },
    { value: 'paused', label: 'Paused' },
    { value: 'not_added', label: 'Not added' },
]

// Narrow, the cells of a row stack into one block, so only the wide layout draws a line between them.
const LATER_CELL = 'pt-0 @min-[48rem]:border-t @min-[48rem]:border-primary @min-[48rem]:pt-2.5'

function RepositoryRow({ repo }: { repo: CodeReviewApprovalRepositoryApi }): JSX.Element {
    return (
        <>
            <div className={`flex min-w-0 items-start px-4 pt-2.5 @min-[48rem]:pb-2.5 ${PANE_LEFT} ${PANE_ROW}`}>
                <span
                    className="min-h-7 min-w-0 truncate font-mono text-sm leading-7 font-semibold"
                    title={repo.repository}
                >
                    {repo.repository}
                </span>
            </div>
            <div className={`min-w-0 px-4 pb-2.5 ${PANE_LEFT} ${LATER_CELL}`}>
                <ApproveCell repo={repo} />
            </div>
            <div className={`min-w-0 px-4 pb-2.5 ${PANE_LEFT} ${LATER_CELL}`}>
                <ReviewerRequestsCell repo={repo} />
            </div>
            <div className={`flex min-h-7 min-w-0 items-start gap-2 px-4 pb-2.5 ${PANE_LEFT} ${LATER_CELL}`}>
                <span className="flex min-h-7 items-center gap-2">
                    <span className="text-xs text-secondary @min-[48rem]:hidden">Digest</span>
                    <DigestCell repo={repo} />
                </span>
            </div>
        </>
    )
}

function RepositoryRows(): JSX.Element | null {
    const { repoConfigs, repoConfigsLoading, repoConfigsFailed, filteredRepoConfigs, visibleRepoConfigs, repoView } =
        useValues(stamphogSceneLogic)
    const { loadRepoConfigs } = useActions(stamphogSceneLogic)

    if (repoConfigsFailed && repoConfigs.length === 0) {
        return (
            <div className={`col-span-full px-4 py-3 ${PANE_LEFT} ${PANE_ROW}`}>
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => loadRepoConfigs() }}
                    data-attr="stamphog-repo-configs-error"
                >
                    Could not load the repositories. This is usually temporary.
                </LemonBanner>
            </div>
        )
    }
    if (repoConfigsLoading && repoConfigs.length === 0) {
        return (
            <div className={`col-span-full flex flex-col gap-2 px-4 py-3 ${PANE_LEFT} ${PANE_ROW}`}>
                <LemonSkeleton className="h-8 w-full" />
                <LemonSkeleton className="h-8 w-full" />
            </div>
        )
    }
    // The not added view is the last row alone, and an empty project shows that row as its start.
    if (filteredRepoConfigs.length === 0) {
        return repoView === 'not_added' || repoConfigs.length === 0 ? null : (
            <div className={`col-span-full px-4 py-3 text-xs text-secondary ${PANE_LEFT} ${PANE_ROW}`}>
                No repositories match.
            </div>
        )
    }
    return (
        <>
            {visibleRepoConfigs.map((repo) => (
                <RepositoryRow key={repo.id} repo={repo} />
            ))}
        </>
    )
}

function RepositoryPager(): JSX.Element | null {
    const { filteredRepoConfigs, visibleRepoConfigs, repoPage, repoPageCount, repoConfigsLoading } =
        useValues(stamphogSceneLogic)
    const { setRepoPage } = useActions(stamphogSceneLogic)
    if (repoPageCount <= 1) {
        return null
    }
    const first = repoPage * REPOS_PAGE_SIZE + 1
    return (
        <RepositoryPageControls
            first={first}
            last={first + visibleRepoConfigs.length - 1}
            total={filteredRepoConfigs.length}
            page={repoPage}
            pageCount={repoPageCount}
            loading={repoConfigsLoading}
            onPageChange={setRepoPage}
        />
    )
}

function RepositoriesTable(): JSX.Element | null {
    const { repoConfigs, repoConfigsLoading, repoConfigsFailed, repoSearch, repoView, hasInstallation } =
        useValues(stamphogSceneLogic)
    const { setRepoSearch, setRepoView, openDigestHistory } = useActions(stamphogSceneLogic)

    // Without the app nothing can be added, and the connection card above says how to install it.
    // A failed load keeps the table, because its rows hold the error and the retry.
    if (hasInstallation === false && repoConfigs.length === 0 && !repoConfigsLoading && !repoConfigsFailed) {
        return null
    }

    return (
        <div className="@container">
            <div className="grid grid-cols-1 overflow-hidden rounded border border-primary @min-[48rem]:grid-cols-[minmax(0,0.8fr)_minmax(0,1.4fr)_minmax(0,1fr)_auto] [&>*:first-child]:border-t-0">
                <RepositoryListFilters
                    search={repoSearch}
                    onSearchChange={setRepoSearch}
                    view={repoView}
                    views={VIEW_OPTIONS}
                    onViewChange={setRepoView}
                    actions={
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconClock />}
                            onClick={openDigestHistory}
                            data-attr="stamphog-open-digest-history"
                        >
                            Digest history
                        </LemonButton>
                    }
                    data-attr="stamphog-repo-search"
                />
                <RepositoryColumnHeaders
                    columns={[
                        { label: 'Repository', pane: 'left' },
                        { label: 'Approve', pane: 'left' },
                        { label: 'Reviewer requests', pane: 'left' },
                        { label: 'Digest', pane: 'left' },
                    ]}
                />
                <RepositoryRows />
                {hasInstallation && (repoView === 'all' || repoView === 'not_added') && <NotAddedRepositoriesRow />}
                <RepositoryPager />
            </div>
        </div>
    )
}

export function AutoApprovalArea(): JSX.Element {
    const { stamphogAccessLevel } = useValues(stamphogSceneLogic)
    const canManage = managerDisabledReason(stamphogAccessLevel) === null

    return (
        <SceneSection
            title={
                <span className="flex flex-wrap items-center gap-2">
                    Auto-approval
                    <LemonTag type="muted" size="small">
                        {canManage ? 'Manager' : 'Manager access required'}
                    </LemonTag>
                </span>
            }
            description="Approves pull requests that are safe to merge without a human, and asks the right owners to review the rest. Set per repository for the whole project, with no personal choice. Uses its own GitHub app."
        >
            <SyncedBanner />
            <AutoApprovalConnectionCard />
            <RepositoriesTable />
            <DigestHistoryModal />
        </SceneSection>
    )
}
