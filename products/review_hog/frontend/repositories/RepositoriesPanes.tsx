import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { MyDefaultCell } from './MyDefaultCell'
import { PANE_LEFT, PANE_RIGHT, PANE_ROW } from './paneClasses'
import { ProjectRuleCell } from './ProjectRuleCell'
import { RepositoryFoldRow } from './RepositoryFoldRow'
import { RepositoryListPager } from './RepositoryListPager'
import { RepositoryListToolbar } from './RepositoryListToolbar'
import { RepositoryMyCell } from './RepositoryMyCell'
import { RepositoryProjectCell } from './RepositoryProjectCell'
import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

function RepositoryRow({ entry }: { entry: ReviewRepositoryOverviewEntryApi }): JSX.Element {
    return (
        <>
            <div className={`flex min-w-0 items-start px-4 pt-2.5 @min-[48rem]:pb-2.5 ${PANE_LEFT} ${PANE_ROW}`}>
                <span
                    className={`min-h-7 min-w-0 truncate font-mono text-sm leading-7 font-semibold ${entry.in_project ? '' : 'text-secondary'}`}
                    title={entry.full_name}
                >
                    {entry.full_name}
                </span>
            </div>
            <RepositoryProjectCell
                entry={entry}
                className={`${PANE_LEFT} pt-0 @min-[48rem]:border-t @min-[48rem]:border-primary @min-[48rem]:pt-2.5`}
            />
            {/* Narrow, the two cells form one block, so only the wide layout draws a line between them. */}
            <RepositoryMyCell
                entry={entry}
                className={`${PANE_RIGHT} pt-0 @min-[48rem]:border-t @min-[48rem]:border-primary @min-[48rem]:pt-2.5`}
            />
        </>
    )
}

function RepositoryRows(): JSX.Element {
    const { overview, overviewLoading, overviewLoadFailed, folding, foldOpen, foldSummary } =
        useValues(reviewHogRepositoriesLogic)
    const { loadOverview } = useActions(reviewHogRepositoriesLogic)
    const foldRow = folding && foldSummary ? <RepositoryFoldRow summary={foldSummary} /> : null

    if (overview === null) {
        if (overviewLoadFailed) {
            return (
                <div className={`col-span-full px-4 py-3 ${PANE_ROW}`}>
                    <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadOverview() }}>
                        Could not load the repositories.
                    </LemonBanner>
                </div>
            )
        }
        return (
            <div className={`col-span-full flex flex-col gap-2 px-4 py-3 ${PANE_ROW}`}>
                {overviewLoading ? (
                    <>
                        <LemonSkeleton className="h-8 w-full" />
                        <LemonSkeleton className="h-8 w-full" />
                        <LemonSkeleton className="h-8 w-full" />
                    </>
                ) : (
                    <span className="text-xs text-secondary">Pick which repositories this project reviews above.</span>
                )}
            </div>
        )
    }
    if (overview.results.length === 0 && !foldRow) {
        return (
            <div className={`col-span-full px-4 py-3 text-xs text-secondary ${PANE_LEFT} ${PANE_ROW}`}>
                No repositories match.
            </div>
        )
    }
    // Closed, the fold row ends the list of repositories that differ. Open, it heads the full list.
    return (
        <>
            {foldOpen && foldRow}
            {overview.results.map((entry) => (
                <RepositoryRow key={entry.full_name} entry={entry} />
            ))}
            {!foldOpen && foldRow}
        </>
    )
}

/**
 * Two panes that share their rows: "This project" holds the rules everyone starts from, "My pull
 * requests" holds the viewer's own choices. Cells go left, right, left, right in one grid, so a row
 * in one pane always matches the height of the same repository's row in the other. On a narrow
 * container the grid falls back to one column, which gives one block per repository.
 */
export function RepositoriesPanes(): JSX.Element {
    const { canEdit } = useValues(reviewHogProjectSettingsLogic)

    return (
        <div className="@container">
            <div className="grid grid-cols-1 overflow-hidden rounded border border-primary @min-[48rem]:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
                <div className={`flex flex-col gap-0.5 px-4 py-3 ${PANE_LEFT}`}>
                    <span className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                        This project
                        <LemonTag type="muted" size="small">
                            {canEdit ? 'Admin' : 'Admin access required'}
                        </LemonTag>
                    </span>
                    <span className="text-xs text-secondary">
                        Defaults for everyone. Your preferences take priority.
                    </span>
                </div>
                <div className={`flex flex-col gap-0.5 px-4 py-3 ${PANE_RIGHT} ${PANE_ROW} @min-[48rem]:border-t-0`}>
                    <span className="flex flex-wrap items-center gap-2 text-sm font-semibold">My pull requests</span>
                    <span className="text-xs text-secondary">
                        Your repository choices take priority over your default below.
                    </span>
                </div>
                <ProjectRuleCell className={`${PANE_LEFT} ${PANE_ROW}`} />
                <MyDefaultCell className={`${PANE_RIGHT} ${PANE_ROW}`} />
            </div>
            <div className="mt-4 grid grid-cols-1 overflow-hidden rounded border border-primary @min-[48rem]:grid-cols-[minmax(0,0.8fr)_minmax(0,1.15fr)_minmax(0,1fr)] [&>*:first-child]:border-t-0">
                <RepositoryListToolbar />
                {/* The personal column uses the same name as the Deep settings tables. */}
                {['Repository', 'Project', 'My preference'].map((column) => (
                    <div
                        key={column}
                        className={`hidden px-4 py-1.5 text-xxs font-semibold tracking-wide text-secondary uppercase @min-[48rem]:block ${column === 'My preference' ? PANE_RIGHT : PANE_LEFT} ${PANE_ROW}`}
                    >
                        {column}
                    </div>
                ))}
                <RepositoryRows />
                <RepositoryListPager />
            </div>
        </div>
    )
}
