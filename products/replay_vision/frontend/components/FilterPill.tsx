import { useState } from 'react'

import { LemonButton, LemonButtonWithDropdown, LemonCheckbox, LemonDivider, LemonInput } from '@posthog/lemon-ui'

export function FilterPill<T extends string>({
    label,
    options,
    value,
    onChange,
    searchable = false,
    searchPlaceholder,
    selectAllLabel,
    dataAttr,
}: {
    label: string
    options: { value: T; label: string }[]
    value: T[]
    onChange: (next: T[]) => void
    searchable?: boolean
    searchPlaceholder?: string
    selectAllLabel?: string
    dataAttr: string
}): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')
    const filteredOptions = searchTerm
        ? options.filter((option) => option.label.toLowerCase().includes(searchTerm.toLowerCase()))
        : options
    const allSelected = options.length > 0 && options.every((option) => value.includes(option.value))
    const showSelectAll = !!selectAllLabel && !searchTerm && options.length > 0
    const toggle = (v: T): void => {
        onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v])
    }
    return (
        <LemonButtonWithDropdown
            type="secondary"
            size="small"
            data-attr={dataAttr}
            dropdown={{
                closeOnClickInside: false,
                onVisibilityChange: (visible) => {
                    if (!visible) {
                        setSearchTerm('')
                    }
                },
                overlay: (
                    <>
                        {searchable && (
                            <LemonInput
                                type="search"
                                size="small"
                                placeholder={searchPlaceholder ?? `Search ${label.toLowerCase()}`}
                                autoFocus
                                fullWidth
                                value={searchTerm}
                                onChange={setSearchTerm}
                                className="mb-1"
                            />
                        )}
                        {showSelectAll && (
                            <>
                                <LemonButton
                                    data-attr={`${dataAttr}-select-all`}
                                    fullWidth
                                    onClick={() => onChange(allSelected ? [] : options.map((option) => option.value))}
                                >
                                    <LemonCheckbox
                                        checked={allSelected ? true : value.length > 0 ? 'indeterminate' : false}
                                        className="pointer-events-none mr-2"
                                    />
                                    {selectAllLabel}
                                </LemonButton>
                                <LemonDivider className="my-1" />
                            </>
                        )}
                        {filteredOptions.map((opt) => (
                            <LemonButton
                                data-attr={`${dataAttr}-option`}
                                key={opt.value}
                                fullWidth
                                onClick={() => toggle(opt.value)}
                            >
                                <LemonCheckbox
                                    checked={value.includes(opt.value)}
                                    className="pointer-events-none mr-2"
                                />
                                {opt.label}
                            </LemonButton>
                        ))}
                    </>
                ),
            }}
        >
            {value.length > 0 ? `${label} (${value.length})` : label}
        </LemonButtonWithDropdown>
    )
}
