import {
    cn,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

export interface QuillEditorSelectOption<T extends string | number> {
    value: T
    label: string
    tooltip?: React.ReactNode
}

export interface QuillEditorSelectProps<T extends string | number> {
    value: T | null
    options: QuillEditorSelectOption<T>[]
    onChange: (value: T) => void
    placeholder?: string
    className?: string
    'data-attr'?: string
}

export function QuillEditorSelect<T extends string | number>({
    value,
    options,
    onChange,
    placeholder = 'Select a value',
    className,
    'data-attr': dataAttr,
}: QuillEditorSelectProps<T>): JSX.Element {
    return (
        <Select<T> value={value} onValueChange={(next: T | null) => next !== null && onChange(next)}>
            <SelectTrigger className={cn('min-w-0', className)} data-attr={dataAttr}>
                <SelectValue className="truncate">
                    {(selected: T | null) =>
                        options.find((option) => option.value === selected)?.label ?? (
                            <span className="text-muted-foreground">{placeholder}</span>
                        )
                    }
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                {options.map((option) =>
                    option.tooltip ? (
                        <Tooltip key={String(option.value)}>
                            <TooltipTrigger render={<SelectItem value={option.value} />}>{option.label}</TooltipTrigger>
                            <TooltipContent side="right" className="max-w-64">
                                {option.tooltip}
                            </TooltipContent>
                        </Tooltip>
                    ) : (
                        <SelectItem key={String(option.value)} value={option.value}>
                            {option.label}
                        </SelectItem>
                    )
                )}
            </SelectContent>
        </Select>
    )
}
