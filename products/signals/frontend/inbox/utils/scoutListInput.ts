import type { KeyboardEventHandler } from 'react'

export function scoutListInputKeyDown(
    draft: string,
    onCommit: () => void,
    onRemoveLast?: () => void
): KeyboardEventHandler<HTMLInputElement> {
    return (event) => {
        if (event.key === 'Enter' || event.key === ',') {
            event.preventDefault()
            onCommit()
        } else if (event.key === 'Backspace' && draft === '' && onRemoveLast) {
            event.preventDefault()
            onRemoveLast()
        }
    }
}
