import { useState } from 'react'

import { Link } from '@posthog/lemon-ui'

import { FullPromptModal } from '../replay_scanners/components/FullPromptModal'
import { LabeledRow } from './LabeledRow'

/** The question the scan answered, with the full prompt a click away from the heading. */
export function ObservationPrompt({
    prompt,
    question,
    size,
}: {
    prompt: string
    question: string | null
    size?: 'small' | 'medium'
}): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <LabeledRow
            label={question ? 'Question' : 'Prompt'}
            size={size}
            aside={
                <Link className="text-xs" onClick={() => setOpen(true)} data-attr="vision-observation-show-prompt">
                    Show full prompt
                </Link>
            }
        >
            {question ? (
                <div>{question}</div>
            ) : (
                // Only an observation scanned with an older prompt lands here: its scanner's question describes the new one.
                // The opening paragraph usually states the goal; the rest is in the full prompt.
                <div className="whitespace-pre-wrap line-clamp-3">{prompt.trim().split(/\n\s*\n/)[0]}</div>
            )}
            <FullPromptModal prompt={prompt} isOpen={open} onClose={() => setOpen(false)} />
        </LabeledRow>
    )
}
