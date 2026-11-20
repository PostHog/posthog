import { useId } from 'react'

import { LemonSegmentedButtonOption } from '@posthog/lemon-ui'
import {
    Button,
    NumberFieldGroup,
    NumberFieldInput,
    NumberFieldRoot,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { LOGS_RETENTION_MAX_MONTHS } from './logsRetentionPeriod'
import { CUSTOM, PickerValue } from './retentionPickerValue'

export interface QuillLogsRetentionPeriodPickerProps {
    value: PickerValue
    options: LemonSegmentedButtonOption<PickerValue>[]
    onSelect: (value: PickerValue) => void
    customSelected: boolean
    customMonths: number | undefined
    customDays: number | undefined
    onCustomMonthsChange: (months: number | undefined) => void
    customDisabledReason: string | null | undefined
    showApply: boolean
    applyDisabledReason: string | null | undefined
    onApply: () => void
    dataAttrPrefix: string
}

function toPickerValue(raw: string): PickerValue {
    return raw === CUSTOM ? CUSTOM : Number(raw)
}

export function QuillLogsRetentionPeriodPicker({
    value,
    options,
    onSelect,
    customSelected,
    customMonths,
    customDays,
    onCustomMonthsChange,
    customDisabledReason,
    showApply,
    applyDisabledReason,
    onApply,
    dataAttrPrefix,
}: QuillLogsRetentionPeriodPickerProps): JSX.Element {
    const monthsId = useId()

    return (
        <div className="flex flex-col gap-2">
            <ToggleGroup
                variant="outline"
                aria-label="Retention period"
                className="w-fit flex-wrap"
                value={[String(value)]}
                onValueChange={(next: string[]) => {
                    if (next[0] && toPickerValue(next[0]) !== value) {
                        onSelect(toPickerValue(next[0]))
                    }
                }}
            >
                {options.map((option) => (
                    <ToggleGroupItem
                        key={String(option.value)}
                        value={String(option.value)}
                        disabledReason={option.disabledReason}
                        data-attr={option['data-attr']}
                    >
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            {customSelected && (
                <div className="flex flex-wrap items-center gap-2">
                    <NumberFieldRoot
                        className="w-24"
                        value={customMonths ?? null}
                        onValueChange={(next: number | null) => onCustomMonthsChange(next ?? undefined)}
                        min={1}
                        max={LOGS_RETENTION_MAX_MONTHS}
                        step={1}
                        disabledReason={customDisabledReason}
                        allowOutOfRange
                    >
                        <NumberFieldGroup>
                            <NumberFieldInput
                                id={monthsId}
                                aria-label="Retention in months"
                                data-attr={`${dataAttrPrefix}-custom-months`}
                            />
                        </NumberFieldGroup>
                    </NumberFieldRoot>
                    <Text size="xs" variant="muted" render={<label htmlFor={monthsId} className="m-0" />}>
                        {`months${customDays !== undefined ? ` (${customDays} days)` : ''}`}
                    </Text>
                    {showApply && (
                        <Button
                            variant="outline"
                            onClick={onApply}
                            disabledReason={applyDisabledReason}
                            data-attr={`${dataAttrPrefix}-custom-apply`}
                        >
                            Apply
                        </Button>
                    )}
                </div>
            )}
        </div>
    )
}
