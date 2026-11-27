import { useState } from 'react'

import { LemonTextArea } from '@posthog/lemon-ui'

import { SCOUT_NOTE_MAX_CHARS } from '../../../logics/scoutNotesLogic'

/**
 * Controlled so LemonTextArea's counter has a value to count; an uncontrolled textarea reports
 * 0 / max no matter what is typed.
 */
export function ScoutNoteComposer({
    onChange,
    placeholder = 'e.g. we shipped a new checkout on Tuesday, watch conversion closely',
    maxLength = SCOUT_NOTE_MAX_CHARS,
}: {
    onChange: (content: string) => void
    placeholder?: string
    maxLength?: number
}): JSX.Element {
    const [content, setContent] = useState('')
    return (
        <LemonTextArea
            autoFocus
            value={content}
            maxLength={maxLength}
            placeholder={placeholder}
            onChange={(value) => {
                setContent(value)
                onChange(value)
            }}
        />
    )
}
