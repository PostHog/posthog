import { IconLogomark } from '@posthog/icons'

/**
 * The name of a right-pane section.
 *
 * The name takes the AI color, which is how the app marks the work its own software did.
 */
export function IssuePaneSectionName({ name }: { name: string }): JSX.Element {
    return (
        <span className="flex shrink-0 items-center gap-1">
            <IconLogomark className="text-lg" />
            <span className="text-sm font-normal text-ai">{name}</span>
        </span>
    )
}
