// PROTOTYPE, never merged: PostHog/michaelr-context#421. Variant A's quick filters: one click per filter, no menus.
import { IconX } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { ME, MessageStatus, STATUSES_BY_TYPE } from './viewsPrototypeData'
import { ViewQuery, allTags, useViewsState } from './viewsPrototypeStore'

function Chip({
    active,
    onClick,
    children,
}: {
    active: boolean
    onClick: () => void
    children: React.ReactNode
}): JSX.Element {
    return (
        <LemonButton
            size="xsmall"
            type={active ? 'primary' : 'secondary'}
            onClick={onClick}
            data-attr="messaging-prototype-quick-filter"
        >
            {children}
        </LemonButton>
    )
}

function toggle<T>(list: T[], value: T): T[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

export function QuickFilterChips({
    query,
    onChange,
    onClear,
}: {
    query: ViewQuery
    onChange: (change: Partial<ViewQuery>) => void
    onClear: () => void
}): JSX.Element {
    const state = useViewsState()
    const statuses = Array.from(new Set(query.types.flatMap((type) => STATUSES_BY_TYPE[type]))) as MessageStatus[]
    const filtered = query.statuses.length > 0 || query.tags.length > 0 || !!query.createdBy || !!query.search
    return (
        <div className="flex flex-wrap items-center gap-1">
            {statuses.map((status) => (
                <Chip
                    key={status}
                    active={query.statuses.includes(status)}
                    onClick={() => onChange({ statuses: toggle(query.statuses, status) })}
                >
                    {status}
                </Chip>
            ))}
            <LemonDivider vertical className="mx-1 h-5" />
            <Chip
                active={query.createdBy === ME}
                onClick={() => onChange({ createdBy: query.createdBy === ME ? null : ME })}
            >
                Created by me
            </Chip>
            <LemonDivider vertical className="mx-1 h-5" />
            {allTags(state).map((tag) => (
                <Chip
                    key={tag}
                    active={query.tags.includes(tag)}
                    onClick={() => onChange({ tags: toggle(query.tags, tag) })}
                >
                    #{tag}
                </Chip>
            ))}
            {filtered && (
                <LemonButton size="xsmall" type="tertiary" icon={<IconX />} onClick={onClear}>
                    Clear filters
                </LemonButton>
            )}
        </div>
    )
}
