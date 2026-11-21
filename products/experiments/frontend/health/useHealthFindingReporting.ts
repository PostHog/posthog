import { useActions, useValues } from 'kea'
import { useCallback, useEffect } from 'react'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import type {
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingOpenKind,
} from './experimentHealthFindingEvents'

export interface HealthFindingReporters {
    reportOpened: (openKind: ExperimentHealthFindingOpenKind) => void
    reportActedOn: (actionKind: ExperimentHealthFindingActionKind) => void
}

/**
 * Reports a finding of the experiment while the caller has it on screen, and returns the reporters
 * for a reader's use of it. Pass null while the experiment has no such finding: the reporters then
 * do nothing. Pass `isShown` as false while the finding exists and the caller shows no sign of it.
 */
export function useHealthFindingReporting(
    finding: ExperimentHealthFinding | null,
    isShown: boolean = true
): HealthFindingReporters {
    const { experimentLoadCount } = useValues(experimentLogic)
    const { reportHealthFindingShown, reportHealthFindingOpened, reportHealthFindingActedOn } =
        useActions(experimentLogic)
    const code = finding?.code
    const subcode = finding?.subcode
    const severity = finding?.severity
    const reason = finding?.reason
    const causedBy = finding?.causedBy

    useEffect(() => {
        if (code && isShown) {
            reportHealthFindingShown({ code, subcode, severity, reason, causedBy })
        }
    }, [code, subcode, severity, reason, causedBy, isShown, experimentLoadCount, reportHealthFindingShown])

    const reportOpened = useCallback(
        (openKind: ExperimentHealthFindingOpenKind): void => {
            if (code) {
                reportHealthFindingOpened({ code, subcode, severity, reason, causedBy }, openKind)
            }
        },
        [code, subcode, severity, reason, causedBy, reportHealthFindingOpened]
    )

    const reportActedOn = useCallback(
        (actionKind: ExperimentHealthFindingActionKind): void => {
            if (code) {
                reportHealthFindingActedOn({ code, subcode, severity, reason, causedBy }, actionKind)
            }
        },
        [code, subcode, severity, reason, causedBy, reportHealthFindingActedOn]
    )

    return { reportOpened, reportActedOn }
}
