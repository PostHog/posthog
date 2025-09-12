import { useValues } from 'kea'

import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'

import { BulkActions } from './components/IssueActions/BulkActions'
import { IssueQueryOptions } from './components/IssueQueryOptions/IssueQueryOptions'
import { errorTrackingBulkSelectLogic } from './errorTrackingBulkSelectLogic'
import { errorTrackingDataNodeLogic } from './errorTrackingDataNodeLogic'

export const ErrorTrackingListOptions = (): JSX.Element => {
    const { selectedIssueIds } = useValues(errorTrackingBulkSelectLogic)
    const { results } = useValues(errorTrackingDataNodeLogic)

    return (
        <SceneStickyBar showBorderBottom={false}>
            {selectedIssueIds.length > 0 ? (
                <BulkActions issues={results} selectedIds={selectedIssueIds} />
            ) : (
                <IssueQueryOptions />
            )}
        </SceneStickyBar>
    )
}
