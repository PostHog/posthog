import { useId, useState } from 'react'

import { IconGlobe } from '@posthog/icons'
import {
    Button,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    RadioGroup,
    RadioGroupItem,
    SelectTriggerIcon,
    Separator,
} from '@posthog/quill'

export interface DomainSelectorOption {
    value: string
    label: string
    icon?: JSX.Element
}

export interface QuillWebAnalyticsDomainSelectorProps {
    value: string
    options: DomainSelectorOption[]
    onChange: (value: string) => void
    footer: JSX.Element
}

export function QuillWebAnalyticsDomainSelector({
    value,
    options,
    onChange,
    footer,
}: QuillWebAnalyticsDomainSelectorProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const id = useId()
    const label = options.find((option) => option.value === value)?.label ?? value

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger render={<Button variant="outline" className="grow md:grow-0" />}>
                <IconGlobe />
                <span className="text-nowrap">{label}</span>
                <SelectTriggerIcon />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto max-w-[90vw]">
                <RadioGroup
                    value={value}
                    onValueChange={(next) => {
                        onChange(next as string)
                        setOpen(false)
                    }}
                >
                    {options.map((option) => (
                        <div key={option.value} className="flex items-center gap-2">
                            <RadioGroupItem value={option.value} id={`${id}-${option.value}`} />
                            <Label
                                htmlFor={`${id}-${option.value}`}
                                className="flex items-center gap-1.5 font-normal whitespace-nowrap"
                            >
                                {option.icon}
                                {option.label}
                            </Label>
                        </div>
                    ))}
                </RadioGroup>
                <Separator />
                {footer}
            </PopoverContent>
        </Popover>
    )
}
