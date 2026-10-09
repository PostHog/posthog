import { useActions, useValues } from 'kea'

import { LemonButton, LemonSearchableSelect } from '@posthog/lemon-ui'

import { githubRepositorySearchLogic } from 'lib/integrations/githubRepositorySearchLogic'
import { urls } from 'scenes/urls'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import { visualReviewSettingsSceneLogic } from '../scenes/visualReviewSettingsSceneLogic'

const HINT_VALUE = '__hint__'

interface Hint {
    label: string
    reason: string
}

function getHint({
    loading,
    error,
    hasMore,
    searchQuery,
    unaddedCount,
}: {
    loading: boolean
    error: string | null
    hasMore: boolean
    searchQuery: string
    unaddedCount: number
}): Hint | null {
    if (loading) {
        return { label: 'Loading repositories...', reason: 'Repositories are loading' }
    }
    if (error) {
        return { label: error, reason: 'Search again or refresh the page' }
    }
    // Only the first page of results loads, so point people at search to reach the rest.
    if (hasMore) {
        return { label: 'Search to find more repositories', reason: 'Only the first results are shown' }
    }
    if (unaddedCount === 0) {
        return searchQuery.trim()
            ? { label: 'No matching repositories to add', reason: 'Try a different search' }
            : { label: 'No more repositories', reason: 'All repositories have been added' }
    }
    return null
}

export interface AddRepoDropdownProps {
    integrationId: number
    placeholder?: string
}

/** Searches the integration's repositories on the server, so installations with many repositories are not cut off. */
export function AddRepoDropdown({ integrationId, placeholder }: AddRepoDropdownProps): JSX.Element {
    const { existingRepoNames, saving, githubManageAccessUrl } = useValues(visualReviewSettingsSceneLogic)
    const { addRepo } = useActions(visualReviewSettingsSceneLogic)
    const searchLogic = githubRepositorySearchLogic({ id: integrationId })
    const { repositories, loading, hasMore, searchQuery, error } = useValues(searchLogic)
    const { setSearchQuery } = useActions(searchLogic)

    const unaddedRepos = repositories.filter((r: GitHubRepoApi) => !existingRepoNames.has(r.full_name))
    const manageAccessUrl = githubManageAccessUrl ?? urls.settings('environment-integrations')

    const hint = getHint({ loading, error, hasMore, searchQuery, unaddedCount: unaddedRepos.length })
    const options = [
        ...unaddedRepos.map((repo: GitHubRepoApi) => ({ value: repo.full_name, label: repo.full_name })),
        ...(hint ? [{ value: HINT_VALUE, label: hint.label, disabledReason: hint.reason }] : []),
    ]

    return (
        <LemonSearchableSelect
            placeholder={placeholder ?? 'Add a repository...'}
            searchPlaceholder="Search repositories"
            data-attr="visual-review-add-repo"
            searchInputDataAttr="visual-review-add-repo-search"
            // The select also reports '' on close, which would otherwise refetch an unchanged list.
            onSearchChange={(query) => query !== searchQuery && setSearchQuery(query)}
            filterOptionsLocally={false}
            loading={saving}
            options={[
                {
                    options,
                    footer: (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            fullWidth
                            to={manageAccessUrl}
                            targetBlank={!!githubManageAccessUrl}
                            className="text-muted"
                        >
                            Manage access
                        </LemonButton>
                    ),
                },
            ]}
            onChange={(fullName) => {
                const repo = repositories.find((r: GitHubRepoApi) => r.full_name === fullName)
                if (repo) {
                    addRepo(repo)
                }
            }}
            value={null}
            size="small"
        />
    )
}
