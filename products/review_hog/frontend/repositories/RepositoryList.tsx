import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import type {
    ReviewHogRepositoryOverviewRetrieveView,
    ReviewRepositoryOverviewEntryApi,
} from 'products/review_hog/frontend/generated/api.schemas'
import { SettingsList } from 'products/review_hog/frontend/settings/SettingsList'

import { RepositoryListPager } from './RepositoryListPager'
import { RepositoryListToolbar } from './RepositoryListToolbar'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

/**
 * The repositories of the connected GitHub account, with their filter and pager. Each tab passes
 * the row it wants: the project's side of a repository, or the viewer's own.
 */
export function RepositoryList({
    Row,
    hiddenView,
}: {
    Row: (props: { entry: ReviewRepositoryOverviewEntryApi }) => JSX.Element
    hiddenView: ReviewHogRepositoryOverviewRetrieveView
}): JSX.Element {
    const { overview, overviewLoadFailed } = useValues(reviewHogRepositoriesLogic)
    const { loadOverview } = useActions(reviewHogRepositoriesLogic)

    let rows: React.ReactNode
    if (overview === null) {
        rows = overviewLoadFailed ? null : (
            <div className="flex flex-col gap-2 px-4 py-3">
                <LemonSkeleton className="h-8 w-full" repeat={3} />
            </div>
        )
    } else if (overview.results.length === 0) {
        rows = <div className="px-4 py-3 text-xs text-secondary">No repositories match.</div>
    } else {
        rows = overview.results.map((entry) => <Row key={entry.full_name} entry={entry} />)
    }

    return (
        <div className="flex flex-col gap-2">
            <RepositoryListToolbar hiddenView={hiddenView} />
            {/* A failed reload keeps the rows of the last good load, so the error shows next to them. */}
            {overviewLoadFailed && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadOverview() }}>
                    {overview === null
                        ? 'Could not load the repositories.'
                        : 'Could not refresh the repositories. The rows below may be out of date.'}
                </LemonBanner>
            )}
            {rows && <SettingsList>{rows}</SettingsList>}
            <RepositoryListPager />
        </div>
    )
}
