import { cn } from '@posthog/quill'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

/** Report markdown at reading size. Agent-written, so images from other hosts stay links. */
export function ReportStageProse({
    markdown,
    tone = 'default',
    size = 'sm',
}: {
    markdown: string
    tone?: 'default' | 'muted'
    size?: 'sm' | 'xs'
}): JSX.Element {
    return (
        <LemonMarkdown
            lowKeyHeadings
            disableImages
            className={cn(
                'leading-relaxed text-pretty',
                size === 'sm' ? 'text-sm' : 'text-xs',
                tone === 'muted' ? 'text-muted-foreground' : 'text-foreground'
            )}
        >
            {markdown}
        </LemonMarkdown>
    )
}
