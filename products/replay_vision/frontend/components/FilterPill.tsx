import { useState } from 'react'

import { LemonButton, LemonButtonWithDropdown, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

export function FilterPill<T extends string>({
    label,
    options,
    value,
    onChange,
    searchable = false,
    loading = false,
}: {
    label: string
    options: { value: T; label: string }[]
    value: T[]
    onChange: (next: T[]) => void
    searchable?: boolean
    loading?: boolean
}): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')
    const filteredOptions = searchTerm
        ? options.filter((option) => option.label.toLowerCase().includes(searchTerm.toLowerCase()))
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
                        setSearchTerm('')
                    }
                },
                overlay: (
                    <>
                        {searchable && (
                            <LemonInput
                                type="search"
                                size="small"
                                placeholder="Search tags"
                                autoFocus
                                fullWidth
                                value={searchTerm}
                                onChange={setSearchTerm}
                                className="mb-1"
                            />
                        )}
                        {filteredOptions.map((opt) => (
                            <LemonButton key={opt.value} fullWidth onClick={() => toggle(opt.value)}>
                                <LemonCheckbox
                                    checked={value.includes(opt.value)}
                                    className="pointer-events-none mr-2"
                                />
                                {opt.label}
                            </LemonButton>
                        ))}
                        {filteredOptions.length === 0 && (
                            <div className="p-2 text-secondary italic truncate">
                                {loading ? 'Loading…' : searchTerm ? 'No matches' : 'No options'}
                            </div>
                        )}
                    </>
                ),
            }}
        >
            {value.length > 0 ? `${label} (${value.length})` : label}
        </LemonButtonWithDropdown>
    )
}
