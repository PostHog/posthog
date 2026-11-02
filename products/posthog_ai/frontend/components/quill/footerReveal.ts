import './footerReveal.scss'

import { cn } from '@posthog/quill-primitives'

/** Props for a message footer that shows while its turn is hovered (see `footerReveal.scss`). */
export function footerRevealProps(
    revealed: boolean,
    className?: string,
    { reserveSpace = false }: { reserveSpace?: boolean } = {}
): { className: string; 'data-revealed'?: true; 'data-reserve-space'?: true } {
    return {
        className: cn('QuillFooterReveal', className),
        'data-revealed': revealed || undefined,
        'data-reserve-space': reserveSpace || undefined,
    }
}
