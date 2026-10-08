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
    const { pivotToGroupBy } = useActions(logsImpactLogic({ id }))

    if (!impact) {
        return null
    }

    // The backend names the dimension carrying the ID on most matching logs, so the pivot groups
    // by the key the data uses. It names none when no matching log carries that ID at all.
    const { sessionGroupKey, personGroupKey } = impact

    return (
        <LogsImpactCounts
            impact={impact}
            onGroupBySessions={sessionGroupKey ? () => pivotToGroupBy(sessionGroupKey) : undefined}
            onGroupByUsers={personGroupKey ? () => pivotToGroupBy(personGroupKey) : undefined}
        />
    )
}
