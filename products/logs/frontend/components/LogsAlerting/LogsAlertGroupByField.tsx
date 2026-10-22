import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { LogsAlertConfigurationThresholdOperatorEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { logsAlertFormLogic } from './logsAlertFormLogic'
import { GROUP_BY_LABELS, GROUPING_NEEDS_ABOVE, LogsAlertGroupBy, MAX_INSTANCES_LIMIT } from './logsAlertGrouping'

const GROUP_BY_HELP: Record<LogsAlertGroupBy, string> = {
    none: 'Split the count by service or severity to alert on each one separately.',
    service:
        'Each service fires and notifies on its own, so several services over the threshold send several notifications.',
    severity:
        'Each severity fires and notifies on its own, so several severities over the threshold send several notifications.',
    service_and_severity:
        'Each service and severity pair fires and notifies on its own, so several pairs over the threshold send several notifications.',
}

export function LogsAlertGroupByField(): JSX.Element | null {
    const { alertForm, alertFormValidationErrors, canGroup } = useValues(logsAlertFormLogic)
    const { setGroupBy, setAlertFormValue } = useActions(logsAlertFormLogic)

    if (!canGroup) {
        return null
    }

    const groupingDisabledReason =
        alertForm.thresholdOperator === LogsAlertConfigurationThresholdOperatorEnumApi.Above
            ? undefined
            : GROUPING_NEEDS_ABOVE
    const isGrouped = alertForm.groupBy !== 'none'

    return (
        <LemonField.Pure
            label="Group by"
            error={alertFormValidationErrors.maxInstances}
            help={<span>{GROUP_BY_HELP[alertForm.groupBy]}</span>}
        >
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <LemonSelect<LogsAlertGroupBy>
                    value={alertForm.groupBy}
                    onChange={(value) => setGroupBy(value)}
                    options={(Object.keys(GROUP_BY_LABELS) as LogsAlertGroupBy[]).map((groupBy) => ({
                        value: groupBy,
                        label: GROUP_BY_LABELS[groupBy],
                        disabledReason: groupBy === 'none' ? undefined : groupingDisabledReason,
                    }))}
                    size="small"
                    data-attr="logs-alert-group-by"
                />
                {isGrouped ? (
                    <span className="inline-flex flex-wrap items-center gap-2 text-sm">
                        <span>Track up to</span>
                        <LemonInput
                            type="number"
                            min={1}
                            max={MAX_INSTANCES_LIMIT}
                            value={alertForm.maxInstances}
                            onChange={(value) => setAlertFormValue('maxInstances', value ?? NaN)}
                            className="w-20"
                            size="small"
                            data-attr="logs-alert-group-max-instances"
                        />
                        <span>groups</span>
                    </span>
                ) : null}
            </div>
        </LemonField.Pure>
    )
}
