import { RefObject, useEffect } from 'react'

/** LemonInput takes no ARIA props, so the combobox roles go on its input directly. */
export function useComboboxInput(
    inputRef: RefObject<HTMLInputElement>,
    listId: string,
    activeOptionId: string | undefined
): void {
    useEffect(() => {
        const input = inputRef.current
        if (!input) {
            return
        }
        input.setAttribute('role', 'combobox')
        input.setAttribute('aria-expanded', 'true')
        input.setAttribute('aria-autocomplete', 'list')
        input.setAttribute('aria-controls', listId)
        if (activeOptionId) {
            input.setAttribute('aria-activedescendant', activeOptionId)
        } else {
            input.removeAttribute('aria-activedescendant')
        }
    }, [inputRef, listId, activeOptionId])
}
