import { useId } from 'react'

import {
    Field,
    InputGroup,
    InputGroupNumberInput,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { QuillChartOptionLabel } from 'lib/components/ChartOptions/QuillChartOptionLabel'

import { FunnelConversionWindowTimeUnit } from '~/types'

export interface QuillFunnelConversionWindowFilterProps {
    info: string
    interval: number | undefined
    bounds: number[]
    unit: FunnelConversionWindowTimeUnit
    unitOptions: { value: FunnelConversionWindowTimeUnit; label: string }[]
    onIntervalChange: (interval: number) => void
    onUnitChange: (unit: FunnelConversionWindowTimeUnit | null) => void
    onCommit: () => void
}

export function QuillFunnelConversionWindowFilter({
    info,
    interval,
    bounds,
    unit,
    unitOptions,
    onIntervalChange,
    onUnitChange,
    onCommit,
}: QuillFunnelConversionWindowFilterProps): JSX.Element {
    const id = useId()

    return (
        <Field
            orientation="horizontal"
            className="flex-wrap justify-between"
            data-attr="funnel-conversion-window-filter"
        >
            <QuillChartOptionLabel htmlFor={id} label="Conversion window limit" info={info} />
            <div className="flex items-center gap-2">
                <InputGroup size="sm" className="w-20">
                    <InputGroupNumberInput
                        id={id}
                        className="h-full"
                        min={bounds[0]}
                        max={bounds[1]}
                        value={interval ?? null}
                        onValueChange={(next) => onIntervalChange(next ?? 0)}
                        onValueCommitted={onCommit}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                onCommit()
                            }
                        }}
                    />
                </InputGroup>
                <Select<FunnelConversionWindowTimeUnit> value={unit} onValueChange={onUnitChange}>
                    <SelectTrigger data-attr="funnel-conversion-window-unit">
                        <SelectValue>
                            {(selected: FunnelConversionWindowTimeUnit) =>
                                unitOptions.find((option) => option.value === selected)?.label ?? selected
                            }
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent align="start" alignItemWithTrigger={false}>
                        {unitOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </div>
        </Field>
    )
}
