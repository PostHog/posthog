import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'
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
}: {
    Row: (props: { entry: ReviewRepositoryOverviewEntryApi }) => JSX.Element
}): JSX.Element {
    const { overview, overviewLoading, overviewLoadFailed } = useValues(reviewHogRepositoriesLogic)
    const { loadOverview } = useActions(reviewHogRepositoriesLogic)

    let rows: React.ReactNode
    if (overview === null && overviewLoadFailed) {
        rows = (
            <div className="px-4 py-3">
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadOverview() }}>
                    Could not load the repositories.
                </LemonBanner>
            </div>
        )
    } else if (overview === null) {
        rows = (
            <div className="flex flex-col gap-2 px-4 py-3">
                {overviewLoading ? (
                    <>
                        <LemonSkeleton className="h-8 w-full" />
                        <LemonSkeleton className="h-8 w-full" />
                        <LemonSkeleton className="h-8 w-full" />
                    </>
                ) : (
                    <span className="text-xs text-secondary">No repositories to show.</span>
                )}
            </div>
        )
    } else if (overview.results.length === 0) {
        rows = <div className="px-4 py-3 text-xs text-secondary">No repositories match.</div>
    } else {
        rows = overview.results.map((entry) => <Row key={entry.full_name} entry={entry} />)
    }

    return (
        <div className="flex flex-col gap-2">
            <RepositoryListToolbar />
            <SettingsList>{rows}</SettingsList>
            <RepositoryListPager />
        </div>
    )
}
