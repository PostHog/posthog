import { useMemo, useRef } from 'react'

import { IconSearch } from '@posthog/icons'

import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
    InputGroupAddon,
} from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

import type { McpFacetOption } from '../mcpFacetsLogic'

export const MCP_FILTER_ACTIVE_CLASS =
    'border-[color-mix(in_oklab,var(--primary)_55%,transparent)]! bg-[color-mix(in_oklab,var(--primary)_10%,transparent)]! font-medium'

export interface McpFacetSelectProps {
    /** Singular, sentence case: "Tool", "Harness". */
    label: string
    options: McpFacetOption[]
    value: string[]
    onChange: (value: string[]) => void
    dataAttr: string
}

export function McpFacetSelect({ label, options, value, onChange, dataAttr }: McpFacetSelectProps): JSX.Element {
    const triggerRef = useRef<HTMLButtonElement>(null)
    // A selected value that dropped out of the window still shows, so it can be cleared.
    const items = useMemo(
        () => [
            ...value.filter((selected) => !options.some((option) => option.value === selected)),
            ...options.map((option) => option.value),
        ],
        [options, value]
    )
    const summary = value.length === 0 ? 'Any' : value.length === 1 ? value[0] : `${value.length} selected`

    return (
        <Combobox<string, true>
            multiple
            items={items}
            value={value}
            onValueChange={onChange}
            autoHighlight
            highlightItemOnHover
        >
            <ComboboxTrigger
                ref={triggerRef}
                render={
                    <Button
                        variant="outline"
                        size="default"
                        left
                        // Values are raw event data, so keep them out of autocapture and replay.
                        className={cn('gap-1.5', value.length > 0 && ['ph-no-capture', MCP_FILTER_ACTIVE_CLASS])}
                        data-attr={dataAttr}
                    />
                }
                aria-label={`${label}: ${summary}`}
            >
                {value.length === 0 ? (
                    <span>{label}</span>
                ) : (
                    <>
                        <span className="text-secondary">{label}</span>
                        <span className="max-w-40 truncate">{summary}</span>
                    </>
                )}
            </ComboboxTrigger>
            <ComboboxContent
                anchor={triggerRef}
                align="start"
                className="w-64 [&_[data-slot=combobox-input-group-wrapper]]:border-b-0"
            >
                <ComboboxInput
                    placeholder={`Search ${label.toLowerCase()}s`}
                    autoFocus
                    showTrigger={false}
                    className="h-7 [&_input]:text-sm"
                >
                    <InputGroupAddon align="inline-start">
                        <IconSearch className="size-3" />
                    </InputGroupAddon>
                </ComboboxInput>
                <ComboboxEmpty>No matches</ComboboxEmpty>
                <ComboboxList>
                    {(item: string) => (
                        <ComboboxItem key={item} value={item} className="text-sm ph-no-capture">
                            {item}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
