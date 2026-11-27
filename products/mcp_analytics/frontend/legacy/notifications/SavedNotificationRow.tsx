import { ReactNode } from 'react'

import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { ConfirmDeleteButton } from 'lib/components/ConfirmDeleteButton'

interface SavedNotificationRowProps {
    icon?: JSX.Element
    name: string
    to: string
    summary?: ReactNode
    enabled: boolean
    onToggle: (enabled: boolean) => void
    toggleLoading: boolean
    toggleDisabled?: boolean
    onDelete: () => void
    deleteDisabledReason?: string
    deleteDataAttr: string
}

export function SavedNotificationRow({
    icon,
    name,
    to,
    summary,
    enabled,
    onToggle,
    toggleLoading,
    toggleDisabled,
    onDelete,
    deleteDisabledReason,
    deleteDataAttr,
}: SavedNotificationRowProps): JSX.Element {
    return (
        <div className="flex items-center gap-3 px-4 py-2">
            {icon}
            <div className="min-w-0 flex-1">
                <Link to={to} className="block truncate text-sm font-medium">
                    {name}
                </Link>
                {summary ? <div className="truncate text-xs text-muted">{summary}</div> : null}
            </div>
            <LemonSwitch
                checked={enabled}
                onChange={() => onToggle(!enabled)}
                loading={toggleLoading}
                disabled={toggleDisabled}
                aria-label={`Enable ${name}`}
            />
            <ConfirmDeleteButton onDelete={onDelete} disabledReason={deleteDisabledReason} data-attr={deleteDataAttr} />
        </div>
    )
}
