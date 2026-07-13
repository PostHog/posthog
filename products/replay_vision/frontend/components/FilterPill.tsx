import { useState } from 'react'

import { LemonButton, LemonButtonWithDropdown, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

const AUTO_SEARCH_OPTION_COUNT = 15

export function FilterPill<T extends string>({
    label,
    options,
    value,
    onChange,
    searchable,
    'data-attr': dataAttr,
}: {
    label: string
    options: { value: T; label: string }[]
    value: T[]
    onChange: (next: T[]) => void
    /** Show a search input in the dropdown. Defaults to automatic: enabled when there are more than 15 options. */
    searchable?: boolean
    'data-attr'?: string
}): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')
    const showSearch = searchable ?? options.length > AUTO_SEARCH_OPTION_COUNT
    const filteredOptions =
        showSearch && searchTerm
            ? options.filter((opt) => opt.label.toLowerCase().includes(searchTerm.toLowerCase()))
            : options
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
                        {showSearch && (
                            <LemonInput
                                type="search"
                                size="small"
                                placeholder="Search"
                                autoFocus
                                fullWidth
                                value={searchTerm}
                                onChange={setSearchTerm}
                                className="mb-1"
                            />
                        )}
                        <div className="max-h-80 overflow-y-auto">
                            {filteredOptions.length > 0 ? (
                                filteredOptions.map((opt) => (
                                    <LemonButton key={opt.value} fullWidth onClick={() => toggle(opt.value)}>
                                        <LemonCheckbox
                                            checked={value.includes(opt.value)}
                                            className="pointer-events-none mr-2"
                                        />
                                        {opt.label}
                                    </LemonButton>
                                ))
                            ) : (
                                <div className="px-2 py-1.5 text-secondary">No results</div>
                            )}
                        </div>
                    </>
                ),
            }}
        >
            {value.length > 0 ? `${label} (${value.length})` : label}
        </LemonButtonWithDropdown>
    )
}
