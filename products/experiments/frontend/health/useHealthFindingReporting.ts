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
    const variant = finding?.variant
    const severity = finding?.severity
    const reason = finding?.reason

    useEffect(() => {
        if (code && isShown) {
            reportHealthFindingShown({ code, variant, severity, reason })
        }
    }, [code, variant, severity, reason, isShown, experimentLoadCount, reportHealthFindingShown])

    const reportOpened = useCallback(
        (openKind: ExperimentHealthFindingOpenKind): void => {
            if (code) {
                reportHealthFindingOpened({ code, variant, severity, reason }, openKind)
            }
        },
        [code, variant, severity, reason, reportHealthFindingOpened]
    )

    const reportActedOn = useCallback(
        (actionKind: ExperimentHealthFindingActionKind): void => {
            if (code) {
                reportHealthFindingActedOn({ code, variant, severity, reason }, actionKind)
            }
        },
        [code, variant, severity, reason, reportHealthFindingActedOn]
    )

    return { reportOpened, reportActedOn }
}
