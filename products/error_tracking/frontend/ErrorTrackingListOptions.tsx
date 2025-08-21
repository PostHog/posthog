import { useValues } from 'kea'

import { BulkActions } from './components/IssueActions/BulkActions'
import { IssueQueryOptions } from './components/IssueQueryOptions/IssueQueryOptions'
import { errorTrackingBulkSelectLogic } from './errorTrackingBulkSelectLogic'
import { errorTrackingDataNodeLogic } from './errorTrackingDataNodeLogic'

export const ErrorTrackingListOptions = (): JSX.Element => {
    const { selectedIssueIds } = useValues(errorTrackingBulkSelectLogic)
    const { results } = useValues(errorTrackingDataNodeLogic)

    return (
        <div className="sticky top-[var(--breadcrumbs-height-compact)] z-20 py-2 bg-primary">
            {selectedIssueIds.length > 0 ? (
                <BulkActions issues={results} selectedIds={selectedIssueIds} />
            ) : (
                <IssueQueryOptions />
            )}
        </div>
    )
}
