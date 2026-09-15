import { useValues } from 'kea'

import { tracingImpactLogic } from '../tracingImpactLogic'
import { TracingImpactCounts } from './TracingImpactCounts'

export interface TracingImpactStripProps {
    id: string
}

/**
 * The impact counts for the viewer's current query. Mounting this component mounts the logic
 * and runs the query, so the caller gates rendering on the flag.
 */
export function TracingImpactStrip({ id }: TracingImpactStripProps): JSX.Element | null {
    const { impact } = useValues(tracingImpactLogic({ id }))

    if (!impact) {
        return null
    }

    return <TracingImpactCounts impact={impact} />
}
