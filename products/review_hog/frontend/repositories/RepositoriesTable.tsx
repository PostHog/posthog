import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { SETTINGS_ROW } from 'products/review_hog/frontend/settings/settingsRowClasses'
import { SettingsTable } from 'products/review_hog/frontend/settings/SettingsTable'

import { RepositoryListPager } from './RepositoryListPager'
import { RepositoryListToolbar } from './RepositoryListToolbar'
import { RepositoryMyCell } from './RepositoryMyCell'
import { RepositoryNameCell } from './RepositoryNameCell'
import { RepositoryProjectCell } from './RepositoryProjectCell'
import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

function RepositoryRows(): JSX.Element {
    const { overview, overviewLoading, overviewLoadFailed } = useValues(reviewHogRepositoriesLogic)
    const { loadOverview } = useActions(reviewHogRepositoriesLogic)

    if (overview === null) {
        if (overviewLoadFailed) {
            return (
                <div className="border-t border-primary px-4 py-3">
                    <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadOverview() }}>
                        Could not load the repositories.
                    </LemonBanner>
                </div>
            )
        }
        return (
            <div className="flex flex-col gap-2 border-t border-primary px-4 py-3">
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
        return <div className="border-t border-primary px-4 py-3 text-xs text-secondary">No repositories match.</div>
    }
    return (
        <>
            {overview.results.map((entry) => (
                <div key={entry.full_name} className={`${SETTINGS_ROW} items-start`}>
                    <RepositoryNameCell entry={entry} />
                    <RepositoryProjectCell entry={entry} />
                    <RepositoryMyCell entry={entry} />
                </div>
            ))}
        </>
    )
}

/**
 * The repositories of the connected GitHub account, one row each: whether this project reviews it,
 * its exception to the project rule, and the viewer's own choice. Hidden until GitHub is connected,
 * because there is nothing to list before that.
 */
export function RepositoriesTable(): JSX.Element | null {
    const { installations } = useValues(reviewHogProjectSettingsLogic)

    if (installations.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-2">
            <RepositoryListToolbar />
            <SettingsTable firstColumn="Repository">
                <RepositoryRows />
            </SettingsTable>
            <RepositoryListPager />
        </div>
    )
}
