import { useActions, useValues } from 'kea'

import { LemonButton, LemonSearchableSelect } from '@posthog/lemon-ui'

import { manageInstallationUrl } from 'lib/integrations/githubInstallationUrl'
import { githubRepositorySearchLogic } from 'lib/integrations/githubRepositorySearchLogic'
import { urls } from 'scenes/urls'

import type { IntegrationType } from '~/types'

import { visualReviewSettingsSceneLogic } from '../scenes/visualReviewSettingsSceneLogic'

const HINT_VALUE = '__hint__'

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
}): string | null {
    if (loading) {
        return 'Loading repositories...'
    }
    if (error) {
        return error
    }
    // Only the first page of results loads, so point people at search to reach the rest.
    if (hasMore) {
        return 'Search to find more repositories'
    }
    if (unaddedCount === 0) {
        return searchQuery.trim() ? 'No matching repositories to add' : 'All repositories have been added'
    }
    return null
}

export interface AddRepoDropdownProps {
    integration: IntegrationType
    /** Names the integration in the placeholder, so several pickers can be told apart. */
    showAccountName?: boolean
}

/** Searches the integration's repositories on the server, so installations with many repositories are not cut off. */
export function AddRepoDropdown({ integration, showAccountName }: AddRepoDropdownProps): JSX.Element {
    const { existingRepoIds, saving } = useValues(visualReviewSettingsSceneLogic)
    const { addRepo } = useActions(visualReviewSettingsSceneLogic)
    const searchLogic = githubRepositorySearchLogic({ id: integration.id })
    const { repositories, loading, hasMore, searchQuery, error } = useValues(searchLogic)
    const { setSearchQuery } = useActions(searchLogic)

    const unaddedRepos = repositories.filter((r) => !existingRepoIds.has(r.id))
    const installationId = integration.config?.installation_id
    const installationUrl = installationId
        ? manageInstallationUrl(installationId, integration.config?.account?.type, integration.config?.account?.name)
        : null
    const manageAccessUrl = installationUrl ?? urls.settings('environment-integrations')

    const hint = getHint({ loading, error, hasMore, searchQuery, unaddedCount: unaddedRepos.length })
    const options = [
        ...unaddedRepos.map((repo) => ({ value: repo.full_name, label: repo.full_name })),
        ...(hint ? [{ value: HINT_VALUE, label: hint, disabledReason: hint }] : []),
    ]

    return (
        <LemonSearchableSelect
            placeholder={showAccountName ? `Add from ${integration.display_name}...` : 'Add a repository...'}
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
                            targetBlank={!!installationUrl}
                            className="text-muted"
                        >
                            Manage access
                        </LemonButton>
                    ),
                },
            ]}
            onChange={(fullName) => {
                const repo = repositories.find((r) => r.full_name === fullName)
                if (repo) {
                    addRepo(repo)
                }
            }}
            value={null}
            size="small"
        />
    )
}
