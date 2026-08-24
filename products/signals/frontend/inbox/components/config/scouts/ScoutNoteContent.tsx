import { useId, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { scoutNotePreview } from './scoutNotePreview'

/** The opening of a note is enough to recognize it; the rest is one click away. */
export function ScoutNoteContent({ content }: { content: string }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const bodyId = useId()
    const bodyRef = useRef<HTMLDivElement>(null)
    const preview = scoutNotePreview(content)
    const truncated = preview !== content

    const toggle = (): void => {
        const next = !expanded
        setExpanded(next)
        // The toggle sits after the note body, so the links a note's tail may hold now sit before
        // the focus. Move focus into the body on expand, so a keyboard user tabs onto them instead
        // of straight past them.
        if (next) {
            bodyRef.current?.focus()
        }
    }

    return (
        <div className="flex flex-col items-start gap-1">
            <div id={bodyId} ref={bodyRef} tabIndex={-1}>
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
                    onClick={toggle}
                >
                    {expanded ? 'Show less' : 'Show more'}
                </LemonButton>
            )}
        </div>
    )
}
