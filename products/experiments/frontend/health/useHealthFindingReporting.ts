import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import type { ExperimentHealthFinding, ExperimentHealthFindingActionKind } from './experimentHealthFindingEvents'

/**
 * Reports the finding that the caller has on screen, and returns the reporter for a use of the
 * finding's action. Pass null while the caller shows no finding: the reporter then does nothing.
 */
export function useHealthFindingReporting(
    finding: ExperimentHealthFinding | null
): (actionKind: ExperimentHealthFindingActionKind) => void {
    const { experimentLoadCount } = useValues(experimentLogic)
    const { reportHealthFindingShown, reportHealthFindingActedOn } = useActions(experimentLogic)
    const code = finding?.code
    const variant = finding?.variant

    useEffect(() => {
        if (code) {
            reportHealthFindingShown({ code, variant })
        }
    }, [code, variant, experimentLoadCount, reportHealthFindingShown])

    return (actionKind) => {
        if (code) {
            reportHealthFindingActedOn({ code, variant }, actionKind)
        }
    }
}
