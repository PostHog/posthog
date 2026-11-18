import { useActions, useValues } from 'kea'

import { RepositoryPageControls } from 'lib/components/RepositoryList/RepositoryPageControls'

import { CodeReviewRepositoryOverviewRetrieveView } from 'products/review_hog/frontend/generated/api.schemas'

import { REPOSITORIES_PAGE_SIZE, reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

export function RepositoryListPager(): JSX.Element | null {
    const { overview, page, pageCount, overviewLoading, requestView } = useValues(reviewHogRepositoriesLogic)
    const { setPage } = useActions(reviewHogRepositoriesLogic)
    if (!overview || overview.total === 0) {
        return null
    }
    // A closed fold leaves the few repositories that differ, which rarely need a second page.
    if (requestView === CodeReviewRepositoryOverviewRetrieveView.Differs && pageCount <= 1) {
        return null
    }
    const first = page * REPOSITORIES_PAGE_SIZE + 1
    return (
        <RepositoryPageControls
            first={first}
            last={Math.min(overview.total, first + overview.results.length - 1)}
            total={overview.total}
            page={page}
            pageCount={pageCount}
            loading={overviewLoading}
            onPageChange={setPage}
        />
    )
}
