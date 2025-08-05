import { useValues } from 'kea'

import { BulkActions } from './components/IssueActions/BulkActions'
import { IssueQueryOptions } from './components/IssueQueryOptions/IssueQueryOptions'
import { errorTrackingDataNodeLogic } from './errorTrackingDataNodeLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

export const ErrorTrackingListOptions = (): JSX.Element => {
    const { selectedIssueIds } = useValues(errorTrackingSceneLogic)
    const { results } = useValues(errorTrackingDataNodeLogic)

    return (
        <div className="sticky top-[var(--breadcrumbs-height-compact)] z-20 py-2 bg-background">
            {selectedIssueIds.length > 0 ? (
                <BulkActions issues={results} selectedIds={selectedIssueIds} />
            ) : (
                <IssueQueryOptions />
            )}
        </div>
    )
}
