import { cn } from '@posthog/quill-primitives'

/**
 * Classes that draw a quill card's border as an inset ring on an overlay above its content. The card's own
 * outer ring is clipped by the chat bubble's overflow, and positioned content such as a chart paints over it.
 */
export function quillCardBorderClass(danger = false): string {
    return cn(
        'relative shadow-none',
        'after:pointer-events-none after:absolute after:inset-0 after:z-10 after:rounded-[inherit]',
        danger
            ? 'after:shadow-[inset_0_0_0_1px_var(--destructive-foreground)]'
            : 'after:shadow-[inset_0_0_0_1px_color-mix(in_oklab,var(--foreground)_10%,transparent)]'
    )
}
