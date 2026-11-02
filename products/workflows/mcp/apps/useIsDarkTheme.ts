import { useEffect, useState } from 'react'

const DARK_QUERY = '(prefers-color-scheme: dark)'

/** Hosts set `data-theme` on the root element. Without one, the app follows the system setting like its styles do. */
function isDarkTheme(): boolean {
    const theme = document.documentElement.getAttribute('data-theme')
    return theme ? theme === 'dark' : !!window.matchMedia?.(DARK_QUERY).matches
}

export function useIsDarkTheme(): boolean {
    const [isDark, setIsDark] = useState(isDarkTheme)
    useEffect(() => {
        const update = (): void => setIsDark(isDarkTheme())
        const observer = new MutationObserver(update)
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
        const media = window.matchMedia?.(DARK_QUERY)
        media?.addEventListener('change', update)
        return () => {
            observer.disconnect()
            media?.removeEventListener('change', update)
        }
    }, [])
    return isDark
}
