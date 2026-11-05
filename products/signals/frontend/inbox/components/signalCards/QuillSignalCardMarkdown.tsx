import { cn } from '@posthog/quill'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

/**
 * Signal content as markdown in the quill cards. Quill has no markdown renderer yet, so this is the one
 * place the quill cards reach for `LemonMarkdown` (as `QuillCitedMarkdown` in replay vision does).
 */
export function QuillSignalCardMarkdown({
    children,
    className,
    codeMaxLines,
}: {
    children: string
    className?: string
    codeMaxLines?: number
}): JSX.Element {
    return (
        <LemonMarkdown
            className={cn('text-xs text-muted-foreground', className)}
            disableImages
            codeMaxLines={codeMaxLines}
        >
            {children}
        </LemonMarkdown>
    )
}
