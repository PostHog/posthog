import { useEffect, useRef, useState } from 'react'

export interface SeriesRenameInputProps {
    initialName: string
    onSave: (name: string) => void
    onCancel: () => void
}

/** Edits an event's name in place in the sentence. Quill's input is a block, so this is an inline one from its tokens. */
export function SeriesRenameInput({ initialName, onSave, onCancel }: SeriesRenameInputProps): JSX.Element {
    const [name, setName] = useState(initialName)
    const inputRef = useRef<HTMLInputElement>(null)
    // Leaving the field saves, so a cancel has to stop the blur that follows it from saving too.
    const cancelledRef = useRef(false)

    useEffect(() => {
        inputRef.current?.select()
    }, [])

    return (
        <input
            ref={inputRef}
            data-quill
            type="text"
            value={name}
            size={Math.max(name.length + 1, 8)}
            aria-label="Name for this event"
            className="inline-block h-8 rounded-(--radius-sm) border border-(--border) bg-(--card) px-1.5 align-baseline text-xl font-semibold text-foreground outline-none focus-visible:border-(--ring) focus-visible:ring-2 focus-visible:ring-(--ring)/30"
            onChange={(event) => setName(event.target.value)}
            onBlur={() => {
                if (!cancelledRef.current) {
                    onSave(name)
                }
            }}
            onKeyDown={(event) => {
                if (event.key === 'Enter') {
                    event.currentTarget.blur()
                } else if (event.key === 'Escape') {
                    cancelledRef.current = true
                    onCancel()
                }
            }}
            data-attr="quill-insight-sentence-rename-event"
        />
    )
}
