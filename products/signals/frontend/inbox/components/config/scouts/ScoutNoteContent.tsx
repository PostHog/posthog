import { useId, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { scoutNotePreview } from './scoutNotePreview'

/** The opening of a note is enough to recognize it; the rest is one click away. */
export function ScoutNoteContent({ content }: { content: string }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const bodyId = useId()
    const preview = scoutNotePreview(content)
    const truncated = preview !== content

    return (
        <div className="flex flex-col items-start gap-1">
            <div id={bodyId}>
                <LemonMarkdown className="text-xs text-secondary" disableImages>
                    {expanded ? content : preview}
                </LemonMarkdown>
            </div>
            {truncated && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    aria-expanded={expanded}
                    aria-controls={bodyId}
                    onClick={() => setExpanded(!expanded)}
                >
                    {expanded ? 'Show less' : 'Show more'}
                </LemonButton>
            )}
        </div>
    )
}
