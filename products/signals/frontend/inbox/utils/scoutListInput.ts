import type { KeyboardEventHandler } from 'react'

export function scoutListInputKeyDown(
    draft: string,
    onCommit: () => void,
    onRemoveLast?: () => void
): KeyboardEventHandler<HTMLInputElement> {
    return (event) => {
        // An IME uses Enter to confirm the active composition. Committing on that Enter would take
        // the unfinished pre-composition text, so bail while composing, the way LemonInput does.
        if (event.nativeEvent.isComposing) {
            return
        }
        if (event.key === 'Enter' || event.key === ',') {
            event.preventDefault()
            onCommit()
        } else if (event.key === 'Backspace' && draft === '' && onRemoveLast) {
            event.preventDefault()
            onRemoveLast()
        }
    }
}
