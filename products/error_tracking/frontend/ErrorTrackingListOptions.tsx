import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

import { BulkActions } from './components/IssueActions/BulkActions'
import { IssueQueryOptions } from './components/IssueQueryOptions/IssueQueryOptions'
import { errorTrackingBulkSelectLogic } from './errorTrackingBulkSelectLogic'
import { errorTrackingDataNodeLogic } from './errorTrackingDataNodeLogic'

export const ErrorTrackingListOptions = (): JSX.Element => {
    const { selectedIssueIds } = useValues(errorTrackingBulkSelectLogic)
    const { results } = useValues(errorTrackingDataNodeLogic)
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    return (
        <div
            className={cn(
                'sticky top-[var(--breadcrumbs-height-compact)] z-20 py-2 bg-primary',
                newSceneLayout && 'top-0 -mx-4 px-4'
            )}
        >
            {selectedIssueIds.length > 0 ? (
                <BulkActions issues={results} selectedIds={selectedIssueIds} />
            ) : (
                <IssueQueryOptions />
            )}
        </div>
    )
}
