import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { LemonBanner, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { MyDefaultCell } from './MyDefaultCell'
import { PANE_LEFT, PANE_RIGHT, PANE_ROW } from './paneClasses'
import { ProjectRuleCell } from './ProjectRuleCell'
import { RepositoryListPager } from './RepositoryListPager'
import { RepositoryListToolbar } from './RepositoryListToolbar'
import { RepositoryMyCell } from './RepositoryMyCell'
import { RepositoryProjectCell } from './RepositoryProjectCell'
import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

function RepositoryRows(): JSX.Element {
    const { overview, overviewLoading, overviewLoadFailed } = useValues(reviewHogRepositoriesLogic)
    const { loadOverview } = useActions(reviewHogRepositoriesLogic)

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
    if (overview.results.length === 0) {
        return (
            <div className={`col-span-full px-4 py-3 text-xs text-secondary ${PANE_LEFT} ${PANE_ROW}`}>
                No repositories match.
            </div>
        )
    }
    return (
        <>
            {overview.results.map((entry) => (
                <Fragment key={entry.full_name}>
                    <RepositoryProjectCell entry={entry} className={`${PANE_LEFT} ${PANE_ROW}`} />
                    {/* Narrow, the two cells form one block, so only the wide layout draws a line between them. */}
                    <RepositoryMyCell
                        entry={entry}
                        className={`${PANE_RIGHT} pt-0 @min-[48rem]:border-t @min-[48rem]:border-primary @min-[48rem]:pt-2.5`}
                    />
                </Fragment>
            ))}
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
                        <LemonTag type="success" size="small">
                            {canEdit ? 'You can edit: project admin' : 'Project admins edit'}
                        </LemonTag>
                    </span>
                    <span className="text-xs text-secondary">
                        Where everyone starts. Each person can still choose for their own PRs. Changes go to the
                        activity log.
                    </span>
                </div>
                <div className={`flex flex-col gap-0.5 px-4 py-3 ${PANE_RIGHT} ${PANE_ROW} @min-[48rem]:border-t-0`}>
                    <span className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                        My pull requests
                        <LemonTag type="highlight" size="small">
                            Only you
                        </LemonTag>
                    </span>
                    <span className="text-xs text-secondary">
                        Highest wins: your repository choice, your default, the repository's exception, the project. A
                        "you" mark shows where you set your own value.
                    </span>
                </div>
                <ProjectRuleCell className={`${PANE_LEFT} ${PANE_ROW}`} />
                <MyDefaultCell className={`${PANE_RIGHT} ${PANE_ROW}`} />
                <RepositoryListToolbar />
                <RepositoryRows />
                <RepositoryListPager />
            </div>
        </div>
    )
}
