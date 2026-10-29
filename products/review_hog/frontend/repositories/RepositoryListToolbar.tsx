import { useActions, useValues } from 'kea'

import { LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { ReviewHogRepositoryOverviewRetrieveView } from 'products/review_hog/frontend/generated/api.schemas'

import { PANE_LEFT, PANE_ROW } from './paneClasses'
import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

const VIEW_OPTIONS: { value: ReviewHogRepositoryOverviewRetrieveView; label: string }[] = [
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
        <div className={`col-span-full flex flex-wrap items-center gap-2 px-4 py-2.5 ${PANE_LEFT} ${PANE_ROW}`}>
            <LemonInput
                type="search"
                size="small"
                className="min-w-48 flex-1"
                placeholder="Filter repositories"
                aria-label="Filter repositories"
                value={search}
                onChange={setSearch}
                data-attr="review-hog-repository-filter"
            />
            {installations.length > 1 && installation && (
                <LemonSelect
                    size="small"
                    aria-label="GitHub account"
                    value={installation.installation_id}
                    options={installations.map((item) => ({ value: item.installation_id, label: item.account_name }))}
                    onChange={selectInstallation}
                />
            )}
            <LemonSegmentedButton size="small" value={view} options={VIEW_OPTIONS} onChange={setView} />
        </div>
    )
}
