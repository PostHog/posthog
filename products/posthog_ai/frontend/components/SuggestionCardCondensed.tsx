import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export interface SuggestionCardCondensedProps {
    icon: JSX.Element
    title: string
    draftName: string
    actionLabel: string
    onExpand: () => void
    onDismiss: () => void
}

export function SuggestionCardCondensed({
    icon,
    title,
    draftName,
    actionLabel,
    onExpand,
    onDismiss,
}: SuggestionCardCondensedProps): JSX.Element {
    return (
        <div
            className="my-2 flex flex-wrap items-center gap-2 rounded border bg-surface-primary px-3 py-2"
            data-attr="posthog-ai-turn-suggestion"
        >
            <span className="shrink-0 text-xl text-accent">{icon}</span>
            <div className="min-w-0 flex-1">
                <div className="font-semibold">{title}</div>
                {draftName && <div className="truncate text-sm text-secondary">{draftName}</div>}
            </div>
            <div className="flex shrink-0 items-center gap-1">
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onExpand}
                    data-attr="posthog-ai-turn-suggestion-expand"
                >
                    {actionLabel}
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconX />}
                    onClick={onDismiss}
                    tooltip="Not now"
                    aria-label="Not now"
                    data-attr="posthog-ai-turn-suggestion-dismiss"
                />
            </div>
        </div>
    )
}
