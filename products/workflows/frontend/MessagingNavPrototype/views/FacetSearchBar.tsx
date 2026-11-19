// PROTOTYPE, never merged: PostHog/michaelr-context#421. Variant C: one search bar holds the whole query. Type, status,
// tag and creator are tokens, so a default view is a query that starts with a type token, and removing it searches
// every message type.
import { useMemo, useRef, useState } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { ME, MessageStatus, MessageType, PEOPLE, STATUSES_BY_TYPE, TYPE_LABELS } from './viewsPrototypeData'
import { ALL_TYPES, ViewQuery, allTags, useViewsState } from './viewsPrototypeStore'

interface Suggestion {
    facet: 'type' | 'status' | 'tag' | 'created by'
    label: string
    apply: (query: ViewQuery) => Partial<ViewQuery>
}

function toggle<T>(list: T[], value: T): T[] {
    return list.includes(value) ? list : [...list, value]
}

export function FacetSearchBar({
    query,
    onChange,
}: {
    query: ViewQuery
    onChange: (change: Partial<ViewQuery>) => void
}): JSX.Element {
    const state = useViewsState()
    const [text, setText] = useState('')
    const [open, setOpen] = useState(false)
    const inputRef = useRef<HTMLInputElement>(null)
    const singleType = query.types.length === 1

    const suggestions: Suggestion[] = useMemo(() => {
        const all: Suggestion[] = [
            ...ALL_TYPES.filter((type) => !singleType || !query.types.includes(type)).map(
                (type): Suggestion => ({
                    facet: 'type',
                    label: TYPE_LABELS[type],
                    apply: (q) => ({ types: q.types.length === ALL_TYPES.length ? [type] : toggle(q.types, type) }),
                })
            ),
            ...(Array.from(new Set(query.types.flatMap((t) => STATUSES_BY_TYPE[t]))) as MessageStatus[]).map(
                (status): Suggestion => ({
                    facet: 'status',
                    label: status,
                    apply: (q) => ({ statuses: toggle(q.statuses, status) }),
                })
            ),
            ...allTags(state).map(
                (tag): Suggestion => ({ facet: 'tag', label: tag, apply: (q) => ({ tags: toggle(q.tags, tag) }) })
            ),
            ...PEOPLE.map(
                (person): Suggestion => ({
                    facet: 'created by',
                    label: person === ME ? 'me' : person,
                    apply: () => ({ createdBy: person }),
                })
            ),
        ]
        const needle = text.trim().toLowerCase()
        return needle ? all.filter((s) => s.label.toLowerCase().includes(needle) || s.facet.startsWith(needle)) : all
    }, [text, query, state, singleType])

    const tokens: { key: string; label: string; remove: () => void }[] = [
        ...(query.types.length === ALL_TYPES.length
            ? []
            : query.types.map((type: MessageType) => ({
                  key: `type-${type}`,
                  label: `type: ${TYPE_LABELS[type]}`,
                  remove: () =>
                      onChange({ types: query.types.length === 1 ? ALL_TYPES : query.types.filter((t) => t !== type) }),
              }))),
        ...query.statuses.map((status) => ({
            key: `status-${status}`,
            label: `status: ${status}`,
            remove: () => onChange({ statuses: query.statuses.filter((s) => s !== status) }),
        })),
        ...query.tags.map((tag) => ({
            key: `tag-${tag}`,
            label: `tag: ${tag}`,
            remove: () => onChange({ tags: query.tags.filter((t) => t !== tag) }),
        })),
        ...(query.createdBy
            ? [
                  {
                      key: 'created-by',
                      label: `created by: ${query.createdBy === ME ? 'me' : query.createdBy}`,
                      remove: () => onChange({ createdBy: null }),
                  },
              ]
            : []),
        ...(query.search
            ? [{ key: 'search', label: `"${query.search}"`, remove: () => onChange({ search: '' }) }]
            : []),
    ]

    const pick = (s: Suggestion): void => {
        onChange(s.apply(query))
        setText('')
        inputRef.current?.focus()
    }

    const grouped = ['type', 'status', 'tag', 'created by']
        .map((facet) => ({ facet, items: suggestions.filter((s) => s.facet === facet) }))
        .filter((g) => g.items.length)

    return (
        <div className="relative w-full">
            <div
                className="flex min-h-9 w-full flex-wrap items-center gap-1 rounded border border-primary bg-surface-primary px-2 py-1 focus-within:border-accent"
                onClick={() => inputRef.current?.focus()}
            >
                <IconSearch className="text-secondary" />
                {tokens.map((token) => (
                    <LemonTag key={token.key} type="highlight" closable onClose={token.remove}>
                        {token.label}
                    </LemonTag>
                ))}
                <input
                    ref={inputRef}
                    className="min-w-40 flex-1 border-none bg-transparent text-sm outline-none"
                    placeholder={
                        tokens.length
                            ? 'Add a filter or search'
                            : 'Search every message, or filter by type, status, tag'
                    }
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onFocus={() => setOpen(true)}
                    onBlur={() => window.setTimeout(() => setOpen(false), 150)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && text.trim()) {
                            onChange({ search: text.trim() })
                            setText('')
                        }
                        if (e.key === 'Backspace' && !text && tokens.length) {
                            tokens[tokens.length - 1].remove()
                        }
                        if (e.key === 'Escape') {
                            inputRef.current?.blur()
                        }
                    }}
                    data-attr="messaging-prototype-facet-search"
                />
            </div>
            {open && (
                <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-80 overflow-y-auto rounded border bg-surface-primary p-1 shadow-lg">
                    {text.trim() && (
                        <LemonButton
                            size="small"
                            fullWidth
                            icon={<IconSearch />}
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => {
                                onChange({ search: text.trim() })
                                setText('')
                            }}
                        >
                            Search for "{text.trim()}"
                        </LemonButton>
                    )}
                    {grouped.map((group) => (
                        <div key={group.facet} className="flex flex-col">
                            <div className="px-2 pt-2 pb-1 text-xxs font-semibold uppercase tracking-wide text-secondary">
                                {group.facet}
                            </div>
                            {group.items.map((s) => (
                                <LemonButton
                                    key={`${s.facet}-${s.label}`}
                                    size="small"
                                    fullWidth
                                    onMouseDown={(e) => e.preventDefault()}
                                    onClick={() => pick(s)}
                                >
                                    {s.facet === 'tag' ? `#${s.label}` : s.label}
                                </LemonButton>
                            ))}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
