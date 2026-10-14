import { useActions, useValues } from 'kea'

import { IconGithub, IconPlus, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInputSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { editorDisabledReason } from './repoAccess'
import { stamphogSceneLogic } from './stamphogSceneLogic'

function addPlaceholder(addableCount: number | null): string {
    if (addableCount === null) {
        return 'Search repositories to add'
    }
    if (addableCount === 0) {
        return 'No repositories left to add'
    }
    return addableCount === 1 ? 'Search 1 repository to add' : `Search ${addableCount} repositories to add`
}

function ConnectGitHubPrompt(): JSX.Element {
    const { openingInstallPage, connectDisabledReason } = useValues(stamphogSceneLogic)
    const { openInstallPage } = useActions(stamphogSceneLogic)
    return (
        <div className="flex flex-wrap items-center justify-between gap-4 border rounded bg-surface-primary p-4">
            <div className="flex flex-col gap-1 min-w-0 max-w-160">
                <h4 className="m-0">Connect GitHub to add repositories</h4>
                <p className="m-0 text-secondary">
                    Install the Stamphog GitHub App on your organization. Then pick the repositories you want reviewed.
                </p>
            </div>
            <LemonButton
                type="primary"
                icon={<IconGithub />}
                onClick={openInstallPage}
                loading={openingInstallPage}
                disabledReason={connectDisabledReason}
                data-attr="stamphog-connect-repository"
            >
                Connect GitHub
            </LemonButton>
        </div>
    )
}

function MissingRepositoryHelp(): JSX.Element {
    const { openingInstallPage, refreshingFromGitHub, connectDisabledReason } = useValues(stamphogSceneLogic)
    const { openInstallPage, refreshFromGitHub } = useActions(stamphogSceneLogic)
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-secondary text-xs">
                Missing a repository? An admin of your GitHub organization can give Stamphog access to it.
            </span>
            <div className="flex flex-wrap items-center gap-1">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconGithub />}
                    onClick={openInstallPage}
                    loading={openingInstallPage}
                    disabledReason={connectDisabledReason}
                    data-attr="stamphog-grant-repository-access"
                >
                    Grant access on GitHub
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconRefresh />}
                    onClick={refreshFromGitHub}
                    loading={refreshingFromGitHub}
                    disabledReason={connectDisabledReason}
                    tooltip="Checks GitHub again for the repositories you can reach"
                    data-attr="stamphog-refresh-repositories"
                >
                    Refresh the list
                </LemonButton>
            </div>
        </div>
    )
}

export function AddRepositoryBar(): JSX.Element {
    const {
        hasInstallation,
        availableRepositories,
        availableRepositoriesLoading,
        availableRepositoriesFailed,
        availableRepositoryOptions,
        addableCount,
        repositoryToAdd,
        addingRepository,
        stamphogAccessLevel,
        availableSearch,
    } = useValues(stamphogSceneLogic)
    const { setAvailableSearch, setRepositoryToAdd, addRepository, loadAvailableRepositories } =
        useActions(stamphogSceneLogic)

    if (availableRepositoriesFailed && hasInstallation === null) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadAvailableRepositories({ search: '' }) }}
                data-attr="stamphog-available-repositories-error"
            >
                Could not load the repositories you can add. This is usually temporary.
            </LemonBanner>
        )
    }
    if (hasInstallation === null) {
        return <LemonSkeleton className="h-24" />
    }
    if (!hasInstallation) {
        return <ConnectGitHubPrompt />
    }

    const shownCount = availableRepositories?.repositories.length ?? 0
    const matchCount = availableRepositories?.total_count ?? 0
    const accessReason = editorDisabledReason(stamphogAccessLevel)

    return (
        <div className="flex flex-col gap-2 border rounded bg-surface-primary p-3">
            <h4 className="m-0">Add a repository</h4>
            {availableRepositoriesFailed && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadAvailableRepositories({ search: availableSearch }),
                    }}
                    data-attr="stamphog-available-repositories-search-error"
                >
                    Could not load the repositories you can add. Try again.
                </LemonBanner>
            )}
            <div className="flex flex-wrap items-center gap-2">
                <LemonInputSelect
                    mode="single"
                    className="flex-1 min-w-60"
                    placeholder={addPlaceholder(addableCount)}
                    options={availableRepositoryOptions}
                    value={repositoryToAdd ? [repositoryToAdd] : []}
                    onChange={(values) => setRepositoryToAdd(values[0] ?? null)}
                    onInputChange={setAvailableSearch}
                    // The server already filtered by the search, so the picker shows its answer as is.
                    disableFiltering
                    loading={availableRepositoriesLoading}
                    title={
                        matchCount > shownCount
                            ? `Showing ${shownCount} of ${matchCount}. Type to narrow the list.`
                            : undefined
                    }
                    emptyStateComponent={
                        <p className="text-secondary italic p-1 m-0">
                            {addableCount === 0 ? 'No repositories left to add.' : 'No repository matches this search.'}
                        </p>
                    }
                    disabledReason={accessReason ?? (addingRepository ? 'Adding the repository' : undefined)}
                    data-attr="stamphog-add-repository-picker"
                />
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={addRepository}
                    loading={addingRepository}
                    disabledReason={accessReason ?? (repositoryToAdd ? undefined : 'Pick a repository first')}
                    data-attr="stamphog-add-repository"
                >
                    Add repository
                </LemonButton>
            </div>
            <MissingRepositoryHelp />
        </div>
    )
}
