import './footerReveal.scss'

import { cn } from '@posthog/quill-primitives'

/** Props for a message footer that shows while its turn is hovered (see `footerReveal.scss`). */
export function footerRevealProps(
    revealed: boolean,
    className?: string
): { className: string; 'data-revealed'?: true } {
    return { className: cn('QuillFooterReveal', className), 'data-revealed': revealed || undefined }
}
