import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill-primitives'

import { type IntervalOption } from 'lib/utils/timeBuckets'

import { IntervalType } from '~/types'

interface McpIntervalFilterProps {
    interval: IntervalType
    options: IntervalOption[]
    onChange: (interval: IntervalType) => void
    dataAttr: string
}

export function McpIntervalFilter({ interval, options, onChange, dataAttr }: McpIntervalFilterProps): JSX.Element {
    return (
        <div className="flex items-center gap-2" data-quill>
            <span className="text-sm text-secondary">Grouped by</span>
            <Select value={interval} onValueChange={(value) => onChange(value as IntervalType)}>
                <SelectTrigger data-attr={dataAttr}>
                    <SelectValue>
                        {(value: IntervalType) => options.find((option) => option.value === value)?.label ?? value}
                    </SelectValue>
                </SelectTrigger>
                <SelectContent>
                    {options.map((option) => (
                        <SelectItem key={option.value} value={option.value} disabled={!!option.disabledReason}>
                            <span className="flex-1">{option.label}</span>
                            {option.disabledReason ? (
                                <span className="text-xs text-secondary">{option.disabledReason}</span>
                            ) : null}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}
