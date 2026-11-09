import { useRef, useState } from 'react'

import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Popover,
    PopoverContent,
    SelectTriggerIcon,
    cn,
} from '@posthog/quill'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import type { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'
import { isInsideOpenPopover } from 'lib/lemon-ui/Popover/Popover'
import { resolveTooltipTitle } from 'lib/lemon-ui/Tooltip/resolveTooltipTitle'

export interface QuillAggregationSelectProps {
    value: string
    title: React.ReactNode
    options: LemonSelectOptionLeaf<string>[]
    footer?: React.ReactNode
    onChange: (value: string) => void
    /** Set when a custom SQL expression can be entered. */
    hogQL?: { value: string; placeholder: string }
    className?: string
}

export function QuillAggregationSelect({
    value,
    title,
    options,
    footer,
    onChange,
    hogQL,
    className,
}: QuillAggregationSelectProps): JSX.Element {
    const triggerRef = useRef<HTMLButtonElement>(null)
    const [hogQLOpen, setHogQLOpen] = useState(false)
    const selected = options.find((option) => option.value === value)

    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            ref={triggerRef}
                            variant="outline"
                            left
                            className={cn('min-w-0 max-w-full', className)}
                            data-attr="retention-aggregation-selector"
                        />
                    }
                >
                    <span className={cn('min-w-0 truncate', !selected && 'font-mono')}>
                        {selected?.label ?? hogQL?.value ?? value}
                    </span>
                    <SelectTriggerIcon />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                    <DropdownMenuGroup>
                        <DropdownMenuLabel inset>{title}</DropdownMenuLabel>
                        <DropdownMenuRadioGroup value={value} onValueChange={(next) => onChange(next as string)}>
                            {options.map((option) => (
                                <DropdownMenuRadioItem
                                    key={option.value}
                                    value={option.value}
                                    closeOnClick
                                    tooltip={resolveTooltipTitle(option.tooltip)}
                                    disabledReason={option.disabledReason}
                                    data-attr={option['data-attr']}
                                >
                                    {option.label}
                                </DropdownMenuRadioItem>
                            ))}
                        </DropdownMenuRadioGroup>
                        {hogQL && (
                            <DropdownMenuItem inset onClick={() => setHogQLOpen(true)}>
                                Custom SQL expression
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuGroup>
                    {footer && (
                        <>
                            <DropdownMenuSeparator />
                            <div data-not-quill className="px-2 py-1">
                                {footer}
                            </div>
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
            {hogQL && (
                <Popover
                    open={hogQLOpen}
                    onOpenChange={(next, details) => {
                        const landedOn =
                            details.reason === 'focus-out'
                                ? (details.event as FocusEvent).relatedTarget
                                : details.reason === 'outside-press'
                                  ? details.event.target
                                  : null
                        if (!next && isInsideOpenPopover(landedOn)) {
                            details.cancel()
                            return
                        }
                        setHogQLOpen(next)
                    }}
                >
                    <PopoverContent anchor={triggerRef} align="start" className="w-auto p-0">
                        {/* eslint-disable-next-line react/forbid-dom-props */}
                        <div data-not-quill className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                            <HogQLEditor
                                value={hogQL.value}
                                placeholder={hogQL.placeholder}
                                onChange={(next) => {
                                    onChange(next)
                                    setHogQLOpen(false)
                                }}
                            />
                        </div>
                    </PopoverContent>
                </Popover>
            )}
        </>
    )
}
