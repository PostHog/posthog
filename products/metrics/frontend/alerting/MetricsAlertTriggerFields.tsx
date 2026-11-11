import { useActions, useValues } from 'kea'

import { LemonInput, LemonInputSelect, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AlertAdvancedOptions } from 'products/alerts/frontend/components/AlertAdvancedOptions'
import { AlertDefinitionRow } from 'products/alerts/frontend/components/AlertDefinition'
import { MetricsPlatformAlertConditionKindEnumApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { metricsAlertFormLogic } from './metricsAlertFormLogic'
import { MetricsAlertFormErrors, OPERATOR_OPTIONS, finiteOrNull } from './metricsAlertUtils'

export function MetricsAlertTriggerFields({ thresholdError }: { thresholdError?: string }): JSX.Element {
    const { alertForm, alertFormErrors } = useValues(metricsAlertFormLogic)
    const { setAlertFormValue } = useActions(metricsAlertFormLogic)
    const isThreshold = alertForm.conditionKind === MetricsPlatformAlertConditionKindEnumApi.Threshold
    // kea-forms fills these only after a save attempt.
    const errors = alertFormErrors as MetricsAlertFormErrors
    const enabledAdvancedOptionsCount =
        Number((alertForm.evaluationPeriods ?? 1) > 1 || (alertForm.datapointsToAlarm ?? 1) > 1) +
        Number((alertForm.cooldownMinutes ?? 0) > 0)

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <h4 className="m-0">Trigger condition</h4>
                <LemonSegmentedButton
                    value={alertForm.conditionKind}
                    onChange={(value) => setAlertFormValue('conditionKind', value)}
                    options={[
                        {
                            value: MetricsPlatformAlertConditionKindEnumApi.Threshold,
                            label: 'Value crosses a threshold',
                        },
                        {
                            value: MetricsPlatformAlertConditionKindEnumApi.Present,
                            label: 'Query returns any series',
                            tooltip: 'Use this when the query already filters to the series in breach.',
                        },
                    ]}
                    size="small"
                    data-attr="metrics-alert-condition-kind"
                />
                {isThreshold ? (
                    <AlertDefinitionRow label="Alert if a series' latest value is">
                        <LemonSelect
                            value={alertForm.operator}
                            onChange={(value) => setAlertFormValue('operator', value)}
                            options={OPERATOR_OPTIONS}
                            size="small"
                            data-attr="metrics-alert-operator"
                        />
                        <LemonInput
                            type="number"
                            value={alertForm.threshold ?? undefined}
                            onChange={(value) => setAlertFormValue('threshold', finiteOrNull(value))}
                            className="w-32"
                            size="small"
                            status={thresholdError ? 'danger' : undefined}
                            data-attr="metrics-alert-threshold"
                        />
                    </AlertDefinitionRow>
                ) : (
                    <p className="text-sm text-secondary m-0">The alert fires for every series the query returns.</p>
                )}
                {isThreshold && thresholdError ? <LemonField.Error error={thresholdError} /> : null}
            </div>
            <LemonField.Pure
                label="Group by labels"
                help="One alert per distinct value of these labels, so each fires and resolves on its own. Leave empty to treat all series as one alert."
            >
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={alertForm.groupByLabels}
                    onChange={(value) => setAlertFormValue('groupByLabels', value)}
                    placeholder="For example service_name"
                    data-attr="metrics-alert-group-by"
                />
            </LemonField.Pure>
            <AlertAdvancedOptions enabledCount={enabledAdvancedOptionsCount}>
                <LemonField.Pure
                    label="Reduce noise"
                    help="Require the condition on several checks before the alert fires. The alert resolves once the condition stops matching."
                    error={errors.datapointsToAlarm ?? errors.evaluationPeriods}
                >
                    <div className="flex items-center gap-2 flex-wrap">
                        <LemonInput
                            type="number"
                            min={1}
                            max={alertForm.evaluationPeriods ?? 10}
                            value={alertForm.datapointsToAlarm ?? undefined}
                            onChange={(value) => setAlertFormValue('datapointsToAlarm', finiteOrNull(value))}
                            className="w-16"
                            size="small"
                        />
                        <span className="text-sm">of</span>
                        <LemonInput
                            type="number"
                            min={1}
                            max={10}
                            value={alertForm.evaluationPeriods ?? undefined}
                            onChange={(value) => {
                                const periods = finiteOrNull(value)
                                setAlertFormValue('evaluationPeriods', periods)
                                if (periods !== null && (alertForm.datapointsToAlarm ?? 0) > periods) {
                                    setAlertFormValue('datapointsToAlarm', periods)
                                }
                            }}
                            className="w-16"
                            size="small"
                        />
                        <span className="text-sm">checks must match to fire</span>
                    </div>
                </LemonField.Pure>
                <LemonField.Pure
                    label="Notification cooldown"
                    help="Minimum time between notifications. Set to 0 for no minimum."
                    error={errors.cooldownMinutes}
                >
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="number"
                            min={0}
                            value={alertForm.cooldownMinutes ?? undefined}
                            onChange={(value) => setAlertFormValue('cooldownMinutes', finiteOrNull(value))}
                            className="w-24"
                            size="small"
                        />
                        <span className="text-sm">minutes</span>
                    </div>
                </LemonField.Pure>
            </AlertAdvancedOptions>
        </div>
    )
}
