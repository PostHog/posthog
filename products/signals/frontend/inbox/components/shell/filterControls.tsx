import { useState } from 'react'

import { IconCheck, IconChevronDown } from '@posthog/icons'
import { LemonDropdown } from '@posthog/lemon-ui'

/** A single filter trigger + dropdown overlay, matching desktop's `InboxFilterPopover`. */
export function FilterPopover({
    label,
    value,
    icon,
    active,
    children,
}: {
    label: string
    value: string
    icon: JSX.Element
    active: boolean
    children: React.ReactNode
}): JSX.Element {
    const [visible, setVisible] = useState(false)
    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={visible}
            onVisibilityChange={setVisible}
            matchWidth={false}
            actionable
            placement="bottom-end"
            overlay={<div className="min-w-[200px] max-w-[260px] p-1 deprecated-space-y-px">{children}</div>}
        >
            <button
                type="button"
                aria-label={`${label}: ${value}`}
                // Quiet at rest: an unused filter is a muted, borderless chip showing its category
                // (e.g. "Source"). Once active it gains a solid border and its selected value — so
                // the bar only draws attention to filters actually in use.
                className={`flex h-8 shrink-0 items-center gap-1.5 rounded border px-2.5 text-sm transition-colors ${
                    active
                        ? 'border-primary bg-surface-primary text-default hover:border-secondary hover:bg-surface-secondary'
                        : 'border-transparent text-muted hover:border-primary hover:bg-surface-secondary hover:text-default'
                }`}
            >
                <span className="flex shrink-0 items-center text-tertiary [&>svg]:size-3.5">{icon}</span>
                <span className="max-w-[150px] truncate">{active ? value : label}</span>
                <IconChevronDown className="shrink-0 text-sm text-tertiary" />
            </button>
        </LemonDropdown>
    )
}

/** A single multi-select row inside a filter popover: icon/glyph + label, with a check when active. */
export function FilterItem({
    icon,
    label,
    active,
    onClick,
}: {
    icon?: JSX.Element
    label: React.ReactNode
    active: boolean
    onClick: () => void
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className="flex w-full items-center justify-between gap-2 rounded px-1.5 py-1 text-left text-sm text-default transition-colors hover:bg-surface-secondary"
        >
            <span className="flex min-w-0 items-center gap-1.5">
                {icon && <span className="flex shrink-0 items-center text-tertiary [&>svg]:size-3.5">{icon}</span>}
                <span className="truncate">{label}</span>
            </span>
            {active && <IconCheck className="shrink-0 text-sm text-default" />}
        </button>
    )
}
