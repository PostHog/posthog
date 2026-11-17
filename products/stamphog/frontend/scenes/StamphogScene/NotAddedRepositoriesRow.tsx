import { useActions, useValues } from 'kea'

import { IconChevronRight, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInputSelect } from '@posthog/lemon-ui'

import { editorDisabledReason } from './repoAccess'
import { stamphogSceneLogic } from './stamphogSceneLogic'

function foldTitle(addableCount: number | null): string {
    if (addableCount === null) {
        return 'Repositories not added'
    }
    if (addableCount === 0) {
        return 'Every repository the app can reach is added'
    }
    return addableCount === 1 ? '1 more repository, not added' : `${addableCount} more repositories, not added`
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
        <div className="flex flex-col gap-2 px-4 pb-3">
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

/**
 * One row for every repository the app can reach that auto-approval does not cover. They all share
 * one state, so the row states it once and opens the picker that adds one.
 */
export function NotAddedRepositoriesRow(): JSX.Element {
    const { addableCount, addRepositoryOpen } = useValues(stamphogSceneLogic)
    const { setAddRepositoryOpen } = useActions(stamphogSceneLogic)
    const canOpen = addableCount !== 0

    return (
        <div className="flex flex-col">
            <button
                type="button"
                onClick={() => setAddRepositoryOpen(!addRepositoryOpen)}
                aria-expanded={addRepositoryOpen}
                disabled={!canOpen}
                className="flex min-w-0 items-center gap-1.5 px-4 py-2.5 text-left enabled:cursor-pointer"
                data-attr="stamphog-not-added-fold"
            >
                {canOpen && (
                    <IconChevronRight
                        className={`shrink-0 text-base transition-transform motion-reduce:transition-none ${addRepositoryOpen ? 'rotate-90' : ''}`}
                    />
                )}
                <span className="text-sm font-semibold">{foldTitle(addableCount)}</span>
                {canOpen && !addRepositoryOpen && (
                    <span className="text-xs text-secondary">· Auto-approval skips them. Open to add one.</span>
                )}
            </button>
            {canOpen && addRepositoryOpen && <AddRepositoryPicker />}
        </div>
    )
}
