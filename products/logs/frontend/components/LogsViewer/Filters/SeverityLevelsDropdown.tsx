import { useCallback, useEffect, useId, useRef, useState } from 'react'

import { IconCheck } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import {
    PopoverPrimitive,
    PopoverPrimitiveContent,
    PopoverPrimitiveTrigger,
} from 'lib/ui/PopoverPrimitive/PopoverPrimitive'
import { capitalizeFirstLetter } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { LogSeverityLevel } from '~/queries/schema/schema-general'

const SEVERITY_OPTIONS: { value: LogSeverityLevel; label: string }[] = [
    { value: 'trace', label: 'Trace' },
    { value: 'debug', label: 'Debug' },
    { value: 'info', label: 'Info' },
    { value: 'warn', label: 'Warn' },
    { value: 'error', label: 'Error' },
    { value: 'fatal', label: 'Fatal' },
]

interface SeverityLevelsDropdownProps {
    value: LogSeverityLevel[]
    onChange: (levels: LogSeverityLevel[]) => void
}

export function SeverityLevelsDropdown({ value, onChange }: SeverityLevelsDropdownProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const listboxRef = useRef<HTMLUListElement>(null)
    const listboxId = useId()

    const toggle = useCallback(
        (level: LogSeverityLevel): void => {
            const next = value.includes(level) ? value.filter((l) => l !== level) : [...value, level]
            onChange(next)
        },
        [value, onChange]
    )

    const displayText =
        value.length === 0 || value.length === SEVERITY_OPTIONS.length
            ? 'All levels'
            : value.length === 1
              ? capitalizeFirstLetter(value[0])
              : `${value.length} levels`

    useEffect(() => {
        if (open) {
            requestAnimationFrame(() => {
                const firstOption = listboxRef.current?.querySelector<HTMLElement>('[role="option"]')
                firstOption?.focus()
            })
        }
    }, [open])

    const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLUListElement>): void => {
        const options = Array.from(listboxRef.current?.querySelectorAll<HTMLElement>('[role="option"]') ?? [])
        const focused = document.activeElement as HTMLElement
        const index = options.indexOf(focused)

        switch (e.key) {
            case 'ArrowDown': {
                e.preventDefault()
                const next = index < options.length - 1 ? index + 1 : 0
                options[next]?.focus()
                break
            }
            case 'ArrowUp': {
                e.preventDefault()
                const prev = index > 0 ? index - 1 : options.length - 1
                options[prev]?.focus()
                break
            }
            case ' ':
            case 'Enter': {
                e.preventDefault()
                focused?.click()
                break
            }
            case 'Home': {
                e.preventDefault()
                options[0]?.focus()
                break
            }
            case 'End': {
                e.preventDefault()
                options[options.length - 1]?.focus()
                break
            }
            case 'Escape': {
                e.preventDefault()
                setOpen(false)
                break
            }
        }
    }, [])

    const selectedCount = value.length === 0 ? SEVERITY_OPTIONS.length : value.length

    return (
        <PopoverPrimitive open={open} onOpenChange={setOpen}>
            <PopoverPrimitiveTrigger asChild>
                <ButtonPrimitive
                    size="sm"
                    variant="outline"
                    data-attr="logs-severity-filter"
                    aria-haspopup="listbox"
                    aria-expanded={open}
                    aria-controls={open ? listboxId : undefined}
                    aria-label={`Severity levels: ${selectedCount} of ${SEVERITY_OPTIONS.length} selected`}
                >
                    {displayText}
                    <MenuOpenIndicator direction="down" />
                </ButtonPrimitive>
            </PopoverPrimitiveTrigger>
            <PopoverPrimitiveContent align="start">
                <ul
                    ref={listboxRef}
                    id={listboxId}
                    role="listbox"
                    aria-multiselectable="true"
                    aria-label="Severity levels"
                    onKeyDown={handleKeyDown}
                    className="flex flex-col gap-px p-1"
                >
                    {SEVERITY_OPTIONS.map(({ value: level, label }) => {
                        const selected = value.length === 0 || value.includes(level)
                        return (
                            <li
                                key={level}
                                role="option"
                                aria-selected={selected}
                                tabIndex={-1}
                                onClick={() => toggle(level)}
                                data-attr={`logs-severity-option-${level}`}
                                className={cn(
                                    'flex items-center gap-1.5 rounded w-full shrink-0 text-left text-sm',
                                    'cursor-pointer select-none outline-none',
                                    'h-[var(--button-height-sm)] px-[var(--button-padding-x-sm)]',
                                    'hover:bg-[var(--color-bg-fill-button-tertiary-hover)]',
                                    'focus-visible:bg-[var(--color-bg-fill-button-tertiary-hover)]'
                                )}
                            >
                                <span
                                    className="flex items-center justify-center shrink-0"
                                    style={{
                                        width: 'var(--button-icon-size-sm)',
                                        height: 'var(--button-icon-size-sm)',
                                    }}
                                >
                                    {selected && <IconCheck className="shrink-0" />}
                                </span>
                                {label}
                            </li>
                        )
                    })}
                </ul>
            </PopoverPrimitiveContent>
        </PopoverPrimitive>
    )
}
