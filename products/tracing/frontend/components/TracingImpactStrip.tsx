import { useValues } from 'kea'

import { tracingImpactLogic } from '../tracingImpactLogic'
import { TracingImpactCounts } from './TracingImpactCounts'

export interface TracingImpactStripProps {
    id: string
}

/** Mounting this mounts the logic and runs the query, so the caller gates it on the flag. */
export function TracingImpactStrip({ id }: TracingImpactStripProps): JSX.Element | null {
    const { impact } = useValues(tracingImpactLogic({ id }))

    if (!impact) {
        return null
    }

    return <TracingImpactCounts impact={impact} />
}
