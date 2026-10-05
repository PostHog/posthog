import { useValues } from 'kea'

import { tracingImpactLogic } from '../tracingImpactLogic'
import { TracingImpactCounts } from './TracingImpactCounts'

/** Mounting this mounts the logic and runs the query, so the caller gates it on the flag. */
export function TracingImpactStrip(): JSX.Element | null {
    const { impact } = useValues(tracingImpactLogic)

    if (!impact) {
        return null
    }

    return <TracingImpactCounts impact={impact} />
}
