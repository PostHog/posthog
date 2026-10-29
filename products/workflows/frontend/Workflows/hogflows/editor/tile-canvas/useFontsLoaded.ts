import { useEffect, useState } from 'react'

/** Captions wrap differently once the web font loads, so every node is measured again then. */
export function useFontsLoaded(): boolean {
    const [loaded, setLoaded] = useState(() => document.fonts?.status === 'loaded')
    useEffect(() => {
        let cancelled = false
        void document.fonts?.ready.then(() => !cancelled && setLoaded(true))
        return () => {
            cancelled = true
        }
    }, [])
    return loaded
}
