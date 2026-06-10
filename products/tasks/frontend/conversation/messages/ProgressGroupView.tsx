import { JSX } from 'react'

import { Step, StepList } from '../StepList'

interface ProgressGroupViewProps {
    steps: Step[]
    /** True while at least one step in this group is `in_progress`. */
    isActive?: boolean
    /** True once the enclosing turn has finished. */
    turnComplete?: boolean
}

/**
 * Renders a progress group (e.g. the cloud sandbox setup steps) as a plain,
 * always-expanded step list. No collapse/accordion — the steps stay visible so
 * the user can always see what stage the run is at.
 */
export function ProgressGroupView({ steps }: ProgressGroupViewProps): JSX.Element | null {
    if (steps.length === 0) {
        return null
    }
    return (
        <div className="my-1 py-1">
            <StepList steps={steps} />
        </div>
    )
}
