import { useValues } from 'kea'

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

    if (!impact) {
        return null
    }

    return <LogsImpactCounts impact={impact} />
}
