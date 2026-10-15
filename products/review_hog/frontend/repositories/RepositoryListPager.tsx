import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { PANE_LEFT, PANE_ROW } from './paneClasses'
import { REPOSITORIES_PAGE_SIZE, reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

export function RepositoryListPager(): JSX.Element | null {
    const { overview, page, pageCount, overviewLoading } = useValues(reviewHogRepositoriesLogic)
    const { setPage } = useActions(reviewHogRepositoriesLogic)
    if (!overview || overview.total === 0) {
        return null
    }
    const first = page * REPOSITORIES_PAGE_SIZE + 1
    const last = Math.min(overview.total, first + overview.results.length - 1)
    return (
        <div
            className={`col-span-full flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-xs text-secondary ${PANE_LEFT} ${PANE_ROW}`}
        >
            <span>
                <span translate="no">
                    {first}-{last} of {overview.total}
                </span>{' '}
                repositories. Nothing is saved for a repository unless it is selected, has an exception, or has a
                personal choice.
            </span>
            <span className="flex gap-1">
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => setPage(page - 1)}
                    disabledReason={page === 0 ? 'This is the first page' : overviewLoading ? 'Loading…' : undefined}
                >
                    Previous
                </LemonButton>
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => setPage(page + 1)}
                    disabledReason={
                        page >= pageCount - 1 ? 'This is the last page' : overviewLoading ? 'Loading…' : undefined
                    }
                >
                    Next
                </LemonButton>
            </span>
        </div>
    )
}
