import { IconChevronDown } from '@posthog/icons'

export interface SuggestionCardCondensedProps {
    icon: JSX.Element
    title: string
    draftName: string
    onExpand: () => void
}

export function SuggestionCardCondensed({
    icon,
    title,
    draftName,
    onExpand,
}: SuggestionCardCondensedProps): JSX.Element {
    return (
        <div className="my-2" data-attr="posthog-ai-turn-suggestion">
            <button
                type="button"
                onClick={onExpand}
                aria-expanded={false}
                className="flex w-full cursor-pointer items-center gap-2 rounded border bg-surface-primary px-3 py-2 text-left hover:bg-surface-secondary"
                data-attr="posthog-ai-turn-suggestion-expand"
            >
                <span className="shrink-0 text-xl text-accent">{icon}</span>
                <span className="flex min-w-0 flex-1 flex-col">
                    <span className="font-semibold">{title}</span>
                    {draftName && <span className="truncate text-sm text-secondary">{draftName}</span>}
                </span>
                <IconChevronDown className="shrink-0 text-xl text-secondary" />
            </button>
        </div>
    )
}
