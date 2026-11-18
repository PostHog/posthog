import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { RepositoryListFilters } from 'lib/components/RepositoryList/RepositoryListFilters'

import { CodeReviewRepositoryOverviewRetrieveView } from 'products/review_hog/frontend/generated/api.schemas'

import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

const VIEW_OPTIONS: { value: CodeReviewRepositoryOverviewRetrieveView; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'in_project', label: 'In this project' },
    { value: 'exceptions', label: 'With exceptions' },
    { value: 'mine', label: 'My choices' },
]

export function RepositoryListToolbar(): JSX.Element {
    const { installations } = useValues(reviewHogProjectSettingsLogic)
    const { installation, search, view } = useValues(reviewHogRepositoriesLogic)
    const { selectInstallation, setSearch, setView } = useActions(reviewHogRepositoriesLogic)

    return (
        <RepositoryListFilters
            search={search}
            onSearchChange={setSearch}
            view={view}
            views={VIEW_OPTIONS}
            onViewChange={setView}
            data-attr="review-hog-repository-filter"
        >
            {installations.length > 1 && installation && (
                <LemonSelect
                    size="small"
                    aria-label="GitHub account"
                    value={installation.installation_id}
                    options={installations.map((item) => ({ value: item.installation_id, label: item.account_name }))}
                    onChange={selectInstallation}
                />
            )}
        </RepositoryListFilters>
    )
}
