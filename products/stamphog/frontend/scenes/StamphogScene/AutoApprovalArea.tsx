import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { type CodeReviewApprovalRepositoryApi } from '../../generated/api.schemas'
import { ApproveSelect } from './ApproveSelect'
import { AutoApprovalConnectionCard } from './AutoApprovalConnectionCard'
import { ExpandedRepoSettings } from './ExpandedRepoSettings'
import { NotAddedRepositoriesRow } from './NotAddedRepositoriesRow'
import { managerDisabledReason } from './repoAccess'
import { ReviewerRequestsSelect } from './ReviewerRequestsSelect'
import { stamphogSceneLogic } from './stamphogSceneLogic'
import { SyncedBanner } from './SyncedBanner'

// A search box only helps once the list no longer fits on one screen.
const REPO_SEARCH_MIN_ROWS = 10

function RepositoryName({ repository }: { repository: string }): JSX.Element {
    const [owner, name] = repository.split('/', 2)
    if (!name) {
        return <span className="font-mono text-sm font-semibold">{repository}</span>
    }
    // A break opportunity after the slash lets a narrow table wrap at the owner instead of mid-word.
    return (
        <span className="font-mono text-sm font-semibold">
            <span>{`${owner}/`}</span>
            <wbr />
            <span>{name}</span>
        </span>
    )
}

function RepositoriesTable(): JSX.Element | null {
    const {
        filteredRepoConfigs,
        repoConfigs,
        repoConfigsLoading,
        repoConfigsFailed,
        repoSearch,
        expandedRepoIds,
        hasInstallation,
    } = useValues(stamphogSceneLogic)
    const { setRepoSearch, setRepoExpanded, loadRepoConfigs } = useActions(stamphogSceneLogic)

    if (repoConfigsFailed && repoConfigs.length === 0) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadRepoConfigs() }}
                data-attr="stamphog-repo-configs-error"
            >
                Could not load the repositories. This is usually temporary.
            </LemonBanner>
        )
    }
    // Without the app nothing can be added, and the connection card above says how to install it.
    if (hasInstallation === false && repoConfigs.length === 0 && !repoConfigsLoading) {
        return null
    }

    const columns: LemonTableColumns<CodeReviewApprovalRepositoryApi> = [
        {
            title: 'Repository',
            dataIndex: 'repository',
            render: (repository) => <RepositoryName repository={repository as string} />,
        },
        {
            title: 'Approve',
            key: 'approve',
            render: (_, repo) => <ApproveSelect repo={repo} />,
        },
        {
            title: 'Reviewer requests',
            key: 'reviewer_requests',
            render: (_, repo) => <ReviewerRequestsSelect repo={repo} />,
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            {repoConfigs.length > REPO_SEARCH_MIN_ROWS && (
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search added repositories"
                    value={repoSearch}
                    onChange={setRepoSearch}
                    className="max-w-100"
                    data-attr="stamphog-repo-search"
                />
            )}
            <LemonTable
                columns={columns}
                dataSource={filteredRepoConfigs}
                loading={repoConfigsLoading}
                rowKey="id"
                expandable={{
                    expandedRowRender: (repo) => <ExpandedRepoSettings repo={repo} />,
                    isRowExpanded: (repo) => expandedRepoIds.includes(repo.id),
                    onRowExpand: (repo) => setRepoExpanded(repo.id, true),
                    onRowCollapse: (repo) => setRepoExpanded(repo.id, false),
                }}
                emptyState={
                    repoConfigs.length > 0
                        ? 'No added repository matches this search.'
                        : 'No repositories added yet. Open the row below to add the first one.'
                }
                footer={hasInstallation ? <NotAddedRepositoriesRow /> : undefined}
                data-attr="stamphog-repo-table"
            />
        </div>
    )
}

/**
 * The Auto-approval area of the Code review settings: the Stamphog GitHub app connection, and one
 * row per added repository with its live Approve and Reviewer requests choices.
 */
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
            description="Approves pull requests that pass an auto-approval review, and can ask code owners to review the rest. These settings apply to the whole project, with no personal preference."
        >
            <SyncedBanner />
            <AutoApprovalConnectionCard />
            <RepositoriesTable />
        </SceneSection>
    )
}
