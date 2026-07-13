import { useState } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonButtonWithDropdown, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

interface FilterPillOption<T extends string> {
    value: T
    label: string
}

export function FilterPill<T extends string>({
    label,
    options,
    value,
    onChange,
    searchable = false,
    searchPlaceholder,
}: {
    label: string
    options: FilterPillOption<T>[]
    value: T[]
    onChange: (next: T[]) => void
    searchable?: boolean
    searchPlaceholder?: string
}): JSX.Element {
    const [search, setSearch] = useState('')
    const normalizedSearch = search.trim().toLowerCase()
    const visibleOptions = normalizedSearch
        ? options.filter((opt) => opt.label.toLowerCase().includes(normalizedSearch))
        : options

    const toggle = (v: T): void => {
        onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v])
    }

    return (
        <LemonButtonWithDropdown
            type="secondary"
            size="small"
            dropdown={{
                closeOnClickInside: false,
                onVisibilityChange: (visible) => {
                    if (!visible) {
                        setSearch('')
                    }
                },
                overlay: (
                    <div className="min-w-64">
                        {searchable && (
                            <div className="p-2 border-b">
                                <LemonInput
                                    type="search"
                                    size="small"
                                    value={search}
                                    onChange={setSearch}
                                    placeholder={searchPlaceholder ?? `Search ${label.toLowerCase()}`}
                                    prefix={<IconSearch />}
                                    autoFocus
                                />
                            </div>
                        )}
                        <div className="py-1">
                            {visibleOptions.length > 0 ? (
                                visibleOptions.map((opt) => (
                                    <LemonButton key={opt.value} fullWidth onClick={() => toggle(opt.value)}>
                                        <LemonCheckbox
                                            checked={value.includes(opt.value)}
                                            className="pointer-events-none mr-2"
                                        />
                                        {opt.label}
                                    </LemonButton>
                                ))
                            ) : (
                                <div className="px-3 py-2 text-sm text-muted">No matching options</div>
                            )}
                        </div>
                    </div>
                ),
            }}
        >
            {value.length > 0 ? `${label} (${value.length})` : label}
        </LemonButtonWithDropdown>
    )
}
