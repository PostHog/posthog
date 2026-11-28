import { useState } from 'react'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

/** The optional note under a feedback prompt, sent only when it has text. */
export function EmailEditorFeedbackNote({
    title,
    placeholder,
    onSend,
    onCancel,
}: {
    title: string
    placeholder: string
    onSend: (note: string) => void
    onCancel: () => void
}): JSX.Element {
    const [note, setNote] = useState('')
    return (
        <div className="flex flex-col gap-2 p-1 w-80" data-attr="email-editor-feedback-note">
            <div className="font-semibold">{title}</div>
            <LemonTextArea value={note} onChange={setNote} placeholder={placeholder} minRows={3} autoFocus />
            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" size="small" onClick={onCancel}>
                    Not now
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="small"
                    disabledReason={note.trim() ? undefined : 'Write a note first'}
                    onClick={() => onSend(note.trim())}
                >
                    Send
                </LemonButton>
            </div>
        </div>
    )
}
