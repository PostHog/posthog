import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInputSelect } from '@posthog/lemon-ui'

import { PANE_LEFT, PANE_ROW } from 'lib/components/RepositoryList/paneClasses'

import { editorDisabledReason } from './repoAccess'
import { stamphogSceneLogic } from './stamphogSceneLogic'

function rowTitle(addableCount: number | null): string {
    if (addableCount === null) {
        return 'Repositories not added'
    }
    if (addableCount === 0) {
        return 'Every repository the app can reach is added'
    }
    return addableCount === 1 ? '1 more repository' : `${addableCount} more repositories`
}

function addPlaceholder(addableCount: number | null): string {
    if (addableCount === null) {
        return 'Search repositories to add'
    }
    return addableCount === 1 ? 'Search 1 repository to add' : `Search ${addableCount} repositories to add`
}

function AddRepositoryPicker(): JSX.Element {
    const {
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
    const shownCount = availableRepositories?.repositories.length ?? 0
    const matchCount = availableRepositories?.total_count ?? 0
    const accessReason = editorDisabledReason(stamphogAccessLevel)

    return (
        <div className={`col-span-full flex flex-col gap-2 px-4 pb-3 ${PANE_LEFT}`}>
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
                    size="small"
                    className="min-w-60 flex-1"
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
                        <p className="m-0 p-1 text-secondary italic">No repository matches this search.</p>
                    }
                    disabledReason={accessReason ?? (addingRepository ? 'Adding the repository' : undefined)}
                    data-attr="stamphog-add-repository-picker"
                />
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={addRepository}
                    loading={addingRepository}
                    disabledReason={accessReason ?? (repositoryToAdd ? undefined : 'Pick a repository first')}
                    data-attr="stamphog-add-repository"
                >
                    Add repository
                </LemonButton>
            </div>
        </div>
    )
}

export function NotAddedRepositoriesRow(): JSX.Element {
    const { addableCount, addRepositoryOpen, stamphogAccessLevel } = useValues(stamphogSceneLogic)
    const { setAddRepositoryOpen } = useActions(stamphogSceneLogic)
    const canAdd = addableCount !== 0

    return (
        <>
            <div className={`flex min-w-0 flex-col px-4 py-2.5 ${PANE_LEFT} ${PANE_ROW}`}>
                <span className="text-sm font-semibold">{rowTitle(addableCount)}</span>
                {canAdd && <span className="text-xs text-secondary">Not added</span>}
            </div>
            <div
                className={`flex min-w-0 flex-wrap items-center gap-2 px-4 pb-2.5 @min-[48rem]:col-span-3 @min-[48rem]:border-t @min-[48rem]:border-primary @min-[48rem]:pt-2.5 ${PANE_LEFT}`}
            >
                {canAdd && (
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlus />}
                            onClick={() => setAddRepositoryOpen(!addRepositoryOpen)}
                            active={addRepositoryOpen}
                            disabledReason={editorDisabledReason(stamphogAccessLevel)}
                            data-attr="stamphog-not-added-fold"
                        >
                            Add
                        </LemonButton>
                        <span className="text-xs text-secondary">
                            The Stamphog app can see them. Nothing is auto-approved there yet.
                        </span>
                    </>
                )}
            </div>
            {canAdd && addRepositoryOpen && <AddRepositoryPicker />}
        </>
    )
}
