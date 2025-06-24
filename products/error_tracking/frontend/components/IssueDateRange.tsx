import { useValues } from 'kea'
import { IconChevronRight } from 'lib/lemon-ui/icons'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { TimeBoundary } from './TimeBoundary'

export function IssueDateRange(): JSX.Element {
    const { firstSeen, issueLoading, summaryLoading, lastSeen } = useValues(errorTrackingIssueSceneLogic)
    return (
        <span className="flex items-center">
            <TimeBoundary
                time={firstSeen}
                label="First Seen"
                loading={issueLoading}
                updateDateRange={(dateRange) => {
                    return {
                        ...dateRange,
                        date_from: firstSeen?.startOf('minute').toISOString(),
                    }
                }}
            />
            <IconChevronRight color="gray" />
            <TimeBoundary
                time={lastSeen}
                label="Last Seen"
                loading={summaryLoading}
                updateDateRange={(dateRange) => {
                    return {
                        ...dateRange,
                        date_to: lastSeen?.endOf('minute').toISOString(),
                    }
                }}
            />
        </span>
    )
}
