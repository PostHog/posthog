import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    FieldLegend,
    FieldSet,
    NumberFieldGroup,
    NumberFieldInput,
    NumberFieldRoot,
    RadioGroup,
    RadioGroupItem,
    Text,
} from '@posthog/quill'

import { logsAlertFormLogic } from './logsAlertFormLogic'
import {
    GROUP_BY_HELP,
    GROUP_BY_LABELS,
    groupByOptionDisabledReason,
    LogsAlertGroupBy,
    MAX_INSTANCES_LIMIT,
} from './logsAlertGrouping'

const GROUP_BY_ITEMS = (Object.keys(GROUP_BY_LABELS) as LogsAlertGroupBy[]).map((groupBy) => ({
    value: groupBy,
    label: GROUP_BY_LABELS[groupBy],
}))

export function QuillLogsAlertGroupByField(): JSX.Element | null {
    const { alertForm, alertFormValidationErrors, canGroup, lockedGroupBy } = useValues(logsAlertFormLogic)
    const { setGroupBy, setAlertFormValue } = useActions(logsAlertFormLogic)
    const idPrefix = useId()

    if (!canGroup) {
        return null
    }

    const isGrouped = alertForm.groupBy !== 'none'
    const maxInstancesError = alertFormValidationErrors.maxInstances as string | undefined

    return (
        <FieldSet data-invalid={maxInstancesError ? true : undefined} className="gap-2">
            <FieldLegend variant="label">Group by</FieldLegend>
            <div className="flex flex-col gap-2">
                <RadioGroup
                    value={alertForm.groupBy}
                    onValueChange={(value) => setGroupBy(value as LogsAlertGroupBy)}
                    className="flex flex-row flex-wrap gap-x-4 gap-y-2"
                    data-attr="logs-alert-group-by"
                >
                    {GROUP_BY_ITEMS.map((item) => {
                        const optionId = `${idPrefix}-${item.value}`

                        return (
                            <Field key={item.value} orientation="horizontal" className="w-fit">
                                <RadioGroupItem
                                    id={optionId}
                                    value={item.value}
                                    disabledReason={groupByOptionDisabledReason(
                                        item.value,
                                        alertForm.thresholdOperator,
                                        lockedGroupBy
                                    )}
                                />
                                <FieldLabel htmlFor={optionId}>{item.label}</FieldLabel>
                            </Field>
                        )
                    })}
                </RadioGroup>
                {isGrouped ? (
                    <span className="inline-flex flex-wrap items-center gap-2">
                        <Text size="xs" render={<span />}>
                            Track up to
                        </Text>
                        <NumberFieldRoot
                            value={Number.isFinite(alertForm.maxInstances) ? alertForm.maxInstances : null}
                            onValueChange={(value: number | null) => setAlertFormValue('maxInstances', value ?? NaN)}
                            min={1}
                            max={MAX_INSTANCES_LIMIT}
                            allowOutOfRange
                            className="w-20"
                        >
                            <NumberFieldGroup>
                                <NumberFieldInput
                                    aria-label="Groups to track"
                                    aria-invalid={maxInstancesError ? true : undefined}
                                    data-attr="logs-alert-group-max-instances"
                                />
                            </NumberFieldGroup>
                        </NumberFieldRoot>
                        <Text size="xs" render={<span />}>
                            groups
                        </Text>
                    </span>
                ) : null}
            </div>
            <FieldDescription>{GROUP_BY_HELP[alertForm.groupBy]}</FieldDescription>
            {maxInstancesError ? <FieldError>{maxInstancesError}</FieldError> : null}
        </FieldSet>
    )
}
