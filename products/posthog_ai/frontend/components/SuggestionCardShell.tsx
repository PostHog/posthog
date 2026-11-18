import { ReactNode } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export interface SuggestionCardShellProps {
    icon: JSX.Element
    title: string
    description: string
    /** Absent once the offer was taken, so a finished card cannot be dismissed. */
    onDismiss?: () => void
    children: ReactNode
}

export function SuggestionCardShell({
    icon,
    title,
    description,
    onDismiss,
    children,
}: SuggestionCardShellProps): JSX.Element {
    return (
        <div
            className="my-2 flex flex-col gap-3 rounded border bg-surface-primary p-3"
            data-attr="posthog-ai-turn-suggestion"
        >
            <div className="flex items-start gap-2">
                <span className="mt-0.5 shrink-0 text-xl text-accent">{icon}</span>
                <div className="min-w-0 flex-1">
                    <div className="font-semibold">{title}</div>
                    <div className="text-sm text-secondary">{description}</div>
                </div>
                {onDismiss && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconX />}
                        onClick={onDismiss}
                        tooltip="Not now"
                        aria-label="Not now"
                        data-attr="posthog-ai-turn-suggestion-dismiss"
                    />
                )}
            </div>
            {children}
        </div>
    )
}
