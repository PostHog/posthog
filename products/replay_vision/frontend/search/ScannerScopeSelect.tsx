import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

export function ScannerScopeSelect({
    scanners,
    value,
    onChange,
}: {
    scanners: { id: string; name: string }[]
    value: string | null
    onChange: (scannerId: string | null) => void
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    const selected = scanners.find((scanner) => scanner.id === value) ?? null
    const needle = search.trim().toLowerCase()
    const matching = scanners
        .filter((scanner) => scanner.name.toLowerCase().includes(needle))
        .sort((a, b) => a.name.localeCompare(b.name))
    const pick = (scannerId: string | null): void => {
        onChange(scannerId)
        setOpen(false)
        setSearch('')
    }

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={open}
            onVisibilityChange={setOpen}
            placement="bottom-start"
            matchWidth={false}
            overlay={
                <div className="w-64 space-y-2">
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder="Search scanners"
                        autoFocus
                        fullWidth
                        value={search}
                        onChange={setSearch}
                    />
                    <ul className="max-h-80 overflow-y-auto">
                        <li>
                            <LemonButton fullWidth size="small" active={value === null} onClick={() => pick(null)}>
                                All scanners
                            </LemonButton>
                        </li>
                        {matching.map((scanner) => (
                            <li key={scanner.id}>
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    active={scanner.id === value}
                                    onClick={() => pick(scanner.id)}
                                >
                                    <span className="truncate">{scanner.name}</span>
                                </LemonButton>
                            </li>
                        ))}
                        {matching.length === 0 && <li className="p-2 text-secondary italic">No matches</li>}
                    </ul>
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                sideIcon={<IconChevronDown />}
                className="shrink-0 max-w-64"
                data-attr="vision-search-scope"
            >
                <span className="truncate">{selected?.name ?? 'All scanners'}</span>
            </LemonButton>
        </LemonDropdown>
    )
}
