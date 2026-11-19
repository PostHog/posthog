import { useMemo, useRef, useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { EmailVariableOption } from '../emailVariables'

const MAX_SHOWN = 100

export function EmailVariablePicker({
    options,
    onPick,
}: {
    options: EmailVariableOption[]
    onPick: (option: EmailVariableOption) => void
}): JSX.Element {
    const [search, setSearch] = useState('')
    const listRef = useRef<HTMLDivElement>(null)
    const matches = useMemo(() => {
        const query = search.trim().toLowerCase()
        return options
            .filter(
                (option) =>
                    !query ||
                    option.label.toLowerCase().includes(query) ||
                    option.expression.toLowerCase().includes(query)
            )
            .slice(0, MAX_SHOWN)
    }, [options, search])
    const groups = [...new Set(matches.map((option) => option.group))]

    const moveFocus = (event: React.KeyboardEvent): void => {
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
            return
        }
        event.preventDefault()
        const items = Array.from(listRef.current?.querySelectorAll<HTMLElement>('button') ?? [])
        const current = items.indexOf(document.activeElement as HTMLElement)
        items[Math.max(0, current + (event.key === 'ArrowDown' ? 1 : -1))]?.focus()
    }

    return (
        <div className="flex flex-col gap-1 p-1 w-72" onKeyDown={moveFocus}>
            <LemonInput
                type="search"
                size="small"
                autoFocus
                fullWidth
                placeholder="Search variables"
                value={search}
                onChange={setSearch}
                data-attr="email-editor-variable-search"
                onPressEnter={() => matches[0] && onPick(matches[0])}
            />
            <div ref={listRef} className="flex flex-col max-h-80 overflow-y-auto">
                {groups.map((group) => (
                    <div key={group} className="flex flex-col">
                        <span className="px-2 pt-2 pb-1 text-xxs font-semibold uppercase text-secondary">{group}</span>
                        {matches
                            .filter((option) => option.group === group)
                            .map((option) => (
                                <LemonButton
                                    key={option.expression}
                                    size="small"
                                    fullWidth
                                    data-attr="email-editor-insert-variable-option"
                                    onClick={() => onPick(option)}
                                >
                                    <span className="truncate">{option.label}</span>
                                </LemonButton>
                            ))}
                    </div>
                ))}
                {!matches.length ? (
                    <span className="p-2 text-xs text-secondary">
                        No variable matches. Type {'{{'} in the email to add your own.
                    </span>
                ) : null}
            </div>
        </div>
    )
}
