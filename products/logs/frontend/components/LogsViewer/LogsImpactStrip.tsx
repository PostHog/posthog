import { useActions, useValues } from 'kea'

import { LogsImpactCounts } from './LogsImpactCounts'
import { logsImpactLogic } from './logsImpactLogic'

export interface LogsImpactStripProps {
    id: string
}

/**
 * The impact counts for the viewer's current query, shown beside the logs count. Mounting this
 * component mounts the logic and runs the query, so the caller gates rendering on the flag.
 */
export function LogsImpactStrip({ id }: LogsImpactStripProps): JSX.Element | null {
    const { impact } = useValues(logsImpactLogic({ id }))
    const { groupBySessions, groupByUsers } = useActions(logsImpactLogic({ id }))

    if (!impact) {
        return null
    }

    // The pivot needs the backend-named dimension; a response without one (an older backend
    // during a deploy) hides the action instead of guessing a dimension.
    return (
        <LogsImpactCounts
            impact={impact}
            onGroupBySessions={impact.sessionGroupKey ? groupBySessions : undefined}
            onGroupByUsers={impact.personGroupKey ? groupByUsers : undefined}
        />
    )
}
