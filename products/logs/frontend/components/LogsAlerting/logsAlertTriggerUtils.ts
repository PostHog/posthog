import { LogsAlertFormType } from './logsAlertFormLogic'

export const WINDOW_OPTIONS = [
    { value: 5, label: '5 minutes' },
    { value: 10, label: '10 minutes' },
    { value: 15, label: '15 minutes' },
    { value: 30, label: '30 minutes' },
    { value: 60, label: '60 minutes' },
]

export function buildCheckPattern(datapoints: number, periods: number): boolean[] {
    // The last check is always matched, since it's the one that tips the alert over.
    // Distribute OK checks evenly across the remaining positions.
    const result: boolean[] = Array(periods).fill(true)
    const okCount = periods - datapoints
    for (let i = 0; i < okCount; i++) {
        const pos = Math.round((i * (periods - 2)) / Math.max(okCount - 1, 1))
        result[pos] = false
    }
    return result
}

export function countEnabledAdvancedOptions(alertForm: LogsAlertFormType): number {
    return (
        Number(alertForm.evaluationPeriods > 1 || alertForm.datapointsToAlarm > 1) +
        Number(alertForm.cooldownMinutes > 0) +
        Number(alertForm.scheduleRestriction !== null)
    )
}

/** Sets the number of checks and keeps the required matches within it. */
export function applyEvaluationPeriods(
    alertForm: LogsAlertFormType,
    value: number | undefined,
    setAlertFormValue: (key: 'evaluationPeriods' | 'datapointsToAlarm', value: number) => void
): void {
    const newPeriods = value ?? alertForm.datapointsToAlarm
    setAlertFormValue('evaluationPeriods', newPeriods)
    if (alertForm.datapointsToAlarm > newPeriods) {
        setAlertFormValue('datapointsToAlarm', newPeriods)
    }
}
