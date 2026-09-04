import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LogsImpactCounts } from './LogsImpactCounts'
import { logsImpactLogic } from './logsImpactLogic'

export interface LogsImpactStripProps {
    id: string
}

/**
 * The impact counts for the viewer's current query, shown beside the logs count. Split from
 * the counts themselves so the logic, and the query it runs, only mount when the flag is on.
 */
export function LogsImpactStrip({ id }: LogsImpactStripProps): JSX.Element | null {
    const enabled = useFeatureFlag('LOGS_IMPACT_STRIP')
    if (!enabled) {
        return null
    }
    return <LogsImpactStripContent id={id} />
}

function LogsImpactStripContent({ id }: LogsImpactStripProps): JSX.Element | null {
    const { impact, personId } = useValues(logsImpactLogic({ id }))

    // The person Logs tab pins a person scope that the impact query does not carry, so the
    // counts there would cover the whole project instead of that person's logs.
    if (personId || !impact) {
        return null
    }

    return <LogsImpactCounts impact={impact} />
}
