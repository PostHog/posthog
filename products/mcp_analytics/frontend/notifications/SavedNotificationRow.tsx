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
        <div className="flex flex-col gap-1 px-3 py-2">
            <div className="flex min-w-0 items-center gap-2">
                {icon}
                <Link to={to} className="block min-w-0 truncate text-sm font-medium">
                    {name}
                </Link>
            </div>
            {summary ? <div className="text-xs text-muted">{summary}</div> : null}
            <div className="flex items-center justify-between gap-2">
                <LemonSwitch
                    checked={enabled}
                    onChange={() => onToggle(!enabled)}
                    loading={toggleLoading}
                    disabled={toggleDisabled}
                    label={enabled ? 'On' : 'Paused'}
                    labelClassName="text-xs text-muted"
                    tooltip={enabled ? 'Pause sending' : 'Resume sending'}
                    aria-label={`Enable ${name}`}
                />
                <ConfirmDeleteButton
                    onDelete={onDelete}
                    disabledReason={deleteDisabledReason}
                    data-attr={deleteDataAttr}
                />
            </div>
        </div>
    )
}
