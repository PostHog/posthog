import { ReactNode } from 'react'

import {
    Button,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

export interface QuillToolbarSelectOption<T> {
    value: T
    label: string
    icon?: ReactNode
    labelInMenu?: ReactNode
    description?: string
}

interface QuillToolbarSelectProps<T> {
    value: T
    options: QuillToolbarSelectOption<T>[]
    onChange: (value: T) => void
    groupLabel?: string
    placeholder?: string
    size?: 'sm' | 'default'
    align?: 'start' | 'end'
    fullWidth?: boolean
    disabled?: boolean
    disabledReason?: string | null
    'data-attr'?: string
}

export function QuillToolbarSelect<T>({
    value,
    options,
    onChange,
    groupLabel,
    placeholder,
    size,
    align = 'start',
    fullWidth,
    disabled,
    disabledReason,
    'data-attr': dataAttr,
}: QuillToolbarSelectProps<T>): JSX.Element {
    // Options are keyed by position, because a value can be null or a boolean and the select only takes strings.
    const selectedIndex = options.findIndex((option) => option.value === value)

    const items = options.map((option, index) => (
        <SelectItem key={index} value={String(index)} className="pe-7">
            {option.icon}
            <span className="flex flex-col items-start gap-0.5">
                <span className="flex items-center gap-1">{option.labelInMenu ?? option.label}</span>
                {option.description && (
                    <Text size="xs" variant="muted" render={<span className="max-w-64 whitespace-normal" />}>
                        {option.description}
                    </Text>
                )}
            </span>
        </SelectItem>
    ))

    return (
        <Select<string>
            value={selectedIndex === -1 ? null : String(selectedIndex)}
            onValueChange={(key) => key !== null && onChange(options[Number(key)].value)}
            disabled={disabled || !!disabledReason}
        >
            <SelectTrigger
                size={size}
                render={<Button variant="outline" size={size} left disabledReason={disabledReason} />}
                className={fullWidth ? 'w-full' : undefined}
                data-attr={dataAttr}
            >
                <SelectValue>
                    {(key: string | null) => {
                        const option = key === null ? undefined : options[Number(key)]
                        return option ? (
                            <span className="flex items-center gap-2">
                                {option.icon}
                                {option.label}
                            </span>
                        ) : (
                            <span className="text-muted-foreground">{placeholder}</span>
                        )
                    }}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align={align} alignItemWithTrigger={false}>
                {groupLabel ? (
                    <SelectGroup>
                        <SelectGroupLabel>{groupLabel}</SelectGroupLabel>
                        {items}
                    </SelectGroup>
                ) : (
                    items
                )}
            </SelectContent>
        </Select>
    )
}
