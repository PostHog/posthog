import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { StamphogTabs } from '../../components/StamphogTabs'
import { type StamphogRepoConfigApi } from '../../generated/api.schemas'
import { AddRepositoryBar } from './AddRepositoryBar'
import { ExpandedRepoSettings } from './ExpandedRepoSettings'
import { repoStatusDisplay, triggerSummary } from './repoDisplay'
import { stamphogSceneLogic } from './stamphogSceneLogic'

// A search box only helps once the list no longer fits on one screen.
const REPO_SEARCH_MIN_ROWS = 10

export const scene: SceneExport = {
    component: StamphogScene,
    logic: stamphogSceneLogic,
}

function RepositoryName({ repository }: { repository: string }): JSX.Element {
    const [owner, name] = repository.split('/', 2)
    if (!name) {
        return <span className="font-medium">{repository}</span>
    }
    // A break opportunity after the slash lets a narrow table wrap at the owner instead of mid-word.
    return (
        <span className="font-medium">
            <span>{`${owner}/`}</span>
            <wbr />
            <span>{name}</span>
        </span>
    )
}

function SyncedBanner(): JSX.Element | null {
    const { syncResult, skippedRepos, appNotInstalled, installUrl, discoveredInstallations } =
        useValues(stamphogSceneLogic)
    const { connectInstallation } = useActions(stamphogSceneLogic)

    // Discovery found several installations and bound nothing: the user picks which one this team
    // connects. The pick rides sessionStorage through one more (silent) authorize hop, and the
    // backend's explicit-id path verifies it.
    if (discoveredInstallations.length > 0) {
        return (
            <LemonBanner type="info">
                <p className="font-medium">Stamphog is installed on several GitHub accounts</p>
                <p>Pick the one to connect to this project:</p>
                <div className="flex gap-2 flex-wrap">
                    {discoveredInstallations.map((installation) => (
                        <LemonButton
                            key={installation.id}
                            type="secondary"
                            icon={<IconGithub />}
                            onClick={() => connectInstallation(installation.id)}
                        >
                            {installation.account_login}
                        </LemonButton>
                    ))}
                </div>
            </LemonBanner>
        )
    }

    // Discovery found no installation the user can reach: they authorized the App but never installed it
    // on the org. Point them at the GitHub install page (install_url still carries a fresh state token).
    if (appNotInstalled) {
        return (
            <LemonBanner type="warning">
                <p className="font-medium">Stamphog isn't installed on GitHub yet</p>
                <p>
                    Install the Stamphog GitHub App on your organization to connect its repositories.
                    {installUrl && (
                        <>
                            {' '}
                            <Link to={installUrl} target="_blank" disableClientSideRouting>
                                Install on GitHub
                            </Link>
                        </>
                    )}
                </p>
            </LemonBanner>
        )
    }

    if (!syncResult) {
        return null
    }

    // A sync only makes repositories available to add and turns no reviews on, so the banner says so.
    const availableCount = syncResult.available_count
    return (
        <LemonBanner type={skippedRepos.length > 0 ? 'warning' : 'success'}>
            <p className="font-medium">GitHub is connected</p>
            <p>
                {availableCount === 0
                    ? 'There are no new repositories to add.'
                    : availableCount === 1
                      ? 'You can now add 1 repository. Reviews start once you add it.'
                      : `You can now add ${availableCount} repositories. Reviews start for each one you add.`}
            </p>
            {skippedRepos.length > 0 && (
                <p className="mt-2">
                    {`Skipped ${skippedRepos.join(', ')} because another project already uses ${skippedRepos.length === 1 ? 'it' : 'them'} with this GitHub installation.`}
                </p>
            )}
        </LemonBanner>
    )
}

function RepoConfigsTable(): JSX.Element {
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
                Could not load your repositories. This is usually temporary.
            </LemonBanner>
        )
    }

    const columns: LemonTableColumns<StamphogRepoConfigApi> = [
        {
            title: 'Repository',
            dataIndex: 'repository',
            render: (repository) => <RepositoryName repository={repository as string} />,
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, repo) => {
                const { type, label } = repoStatusDisplay(repo)
                return <LemonTag type={type}>{label}</LemonTag>
            },
        },
        {
            title: 'Trigger',
            key: 'trigger',
            render: (_, repo) => triggerSummary(repo),
        },
        {
            title: 'Digest',
            key: 'digest_enabled',
            render: (_, repo) => (repo.digest_enabled ? 'On' : <span className="text-secondary">Off</span>),
        },
        {
            title: 'Added',
            dataIndex: 'created_at',
            render: (created_at) => <TZLabel time={created_at as string} />,
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            {repoConfigs.length > REPO_SEARCH_MIN_ROWS && (
                <LemonInput
                    type="search"
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
                        : hasInstallation === false
                          ? 'No repositories yet. Connect GitHub to add the first one.'
                          : 'No repositories yet. Add one above to start reviews.'
                }
                data-attr="stamphog-repo-table"
            />
        </div>
    )
}

export function StamphogScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Stamphog"
                description="Automated pull request reviews and merged-PR digests, per repository."
                resourceType={{ type: 'stamphog' }}
            />
            <StamphogTabs activeKey="repositories" />
            <SyncedBanner />
            <AddRepositoryBar />
            <RepoConfigsTable />
        </SceneContent>
    )
}

export default StamphogScene
