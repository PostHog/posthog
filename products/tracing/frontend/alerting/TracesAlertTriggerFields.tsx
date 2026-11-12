import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AlertAdvancedOptions } from 'products/alerts/frontend/components/AlertAdvancedOptions'
import { AlertDefinitionRow } from 'products/alerts/frontend/components/AlertDefinition'
import { MeasureEnumApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { tracesAlertFormLogic } from './tracesAlertFormLogic'
import {
    GROUP_BY_OPTIONS,
    MAX_EVALUATION_PERIODS,
    MEASURE_OPTIONS,
    OPERATOR_OPTIONS,
    PERCENTILE_OPTIONS,
    WINDOW_OPTIONS,
    errorText,
    finiteOr,
    thresholdUnit,
} from './tracesAlertUtils'

export function TracesAlertTriggerFields({ thresholdError }: { thresholdError?: string }): JSX.Element {
    const { alertForm, alertFormErrors } = useValues(tracesAlertFormLogic)
    const { setAlertFormValue } = useActions(tracesAlertFormLogic)
    const enabledAdvancedOptionsCount =
        Number(alertForm.evaluationPeriods > 1 || alertForm.datapointsToAlarm > 1) +
        Number(alertForm.cooldownMinutes > 0)

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <h4 className="m-0">Trigger condition</h4>
                <AlertDefinitionRow label="Alert when">
                    {alertForm.measure === MeasureEnumApi.Latency ? (
                        <LemonSelect
                            value={alertForm.percentile}
                            onChange={(value) => setAlertFormValue('percentile', value)}
                            options={PERCENTILE_OPTIONS}
                            size="small"
                            data-attr="traces-alert-percentile"
                        />
                    ) : null}
                    <LemonSelect
                        value={alertForm.measure}
                        onChange={(value) => setAlertFormValue('measure', value)}
                        options={MEASURE_OPTIONS}
                        size="small"
                        data-attr="traces-alert-measure"
                    />
                    <span>is</span>
                    <LemonSelect
                        value={alertForm.thresholdOperator}
                        onChange={(value) => setAlertFormValue('thresholdOperator', value)}
                        options={OPERATOR_OPTIONS}
                        size="small"
                        data-attr="traces-alert-operator"
                    />
                    <LemonInput
                        type="number"
                        min={0}
                        max={alertForm.measure === MeasureEnumApi.ErrorRate ? 100 : undefined}
                        value={alertForm.threshold ?? undefined}
                        onChange={(value) => setAlertFormValue('threshold', value ?? null)}
                        className="w-28"
                        size="small"
                        suffix={<span className="text-secondary text-xs">{thresholdUnit(alertForm.measure)}</span>}
                        status={thresholdError ? 'danger' : undefined}
                        data-attr="traces-alert-threshold"
                    />
                    <span>over</span>
                    <LemonSelect
                        value={alertForm.windowMinutes}
                        onChange={(value) => setAlertFormValue('windowMinutes', value)}
                        options={WINDOW_OPTIONS}
                        size="small"
                        data-attr="traces-alert-window"
                    />
                </AlertDefinitionRow>
                {thresholdError ? <LemonField.Error error={thresholdError} /> : null}
                <p className="text-sm text-secondary m-0">Checks run every minute.</p>
            </div>
            <LemonField.Pure
                label="Check separately for"
                help="A grouped alert fires and resolves for each group on its own. Changing this on a saved alert clears its current groups."
                error={errorText(alertFormErrors.groupBy)}
            >
                <LemonSelect
                    value={alertForm.groupBy}
                    onChange={(value) => setAlertFormValue('groupBy', value)}
                    options={GROUP_BY_OPTIONS}
                    size="small"
                    data-attr="traces-alert-group-by"
                />
            </LemonField.Pure>
            <AlertAdvancedOptions enabledCount={enabledAdvancedOptionsCount}>
                <LemonField.Pure
                    label="Reduce noise"
                    help="Require the condition on several checks before the alert fires. The alert resolves once the condition stops matching."
                    error={errorText(alertFormErrors.evaluationPeriods) ?? errorText(alertFormErrors.datapointsToAlarm)}
                >
                    <div className="flex items-center gap-2 flex-wrap">
                        <LemonInput
                            type="number"
                            min={1}
                            max={alertForm.evaluationPeriods}
                            value={alertForm.datapointsToAlarm}
                            onChange={(value) => setAlertFormValue('datapointsToAlarm', finiteOr(value, 1))}
                            className="w-16"
                            size="small"
                            data-attr="traces-alert-datapoints"
                        />
                        <span className="text-sm">of</span>
                        <LemonInput
                            type="number"
                            min={1}
                            max={MAX_EVALUATION_PERIODS}
                            value={alertForm.evaluationPeriods}
                            onChange={(value) => {
                                const periods = finiteOr(value, 1)
                                setAlertFormValue('evaluationPeriods', periods)
                                if (alertForm.datapointsToAlarm > periods) {
                                    setAlertFormValue('datapointsToAlarm', periods)
                                }
                            }}
                            className="w-16"
                            size="small"
                            data-attr="traces-alert-evaluation-periods"
                        />
                        <span className="text-sm">checks must match to fire</span>
                    </div>
                </LemonField.Pure>
                <LemonField.Pure
                    label="Notification cooldown"
                    help="Minimum time between notifications. Set to 0 for no minimum."
                    error={errorText(alertFormErrors.cooldownMinutes)}
                >
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="number"
                            min={0}
                            value={alertForm.cooldownMinutes}
                            onChange={(value) => setAlertFormValue('cooldownMinutes', finiteOr(value, 0))}
                            className="w-24"
                            size="small"
                            data-attr="traces-alert-cooldown"
                        />
                        <span className="text-sm">minutes</span>
                    </div>
                </LemonField.Pure>
            </AlertAdvancedOptions>
        </div>
    )
}
