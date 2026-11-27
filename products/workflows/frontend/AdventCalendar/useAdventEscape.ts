import { useEffect } from 'react'

export function useAdventEscape(isRevealing: boolean, finishReveal: () => void, dismiss: () => void): void {
    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key !== 'Escape') {
                return
            }
            if (isRevealing) {
                finishReveal()
            } else {
                dismiss()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [isRevealing, finishReveal, dismiss])
}
