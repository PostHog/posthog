import { useSyncExternalStore } from 'react'
import { AppState } from 'react-native'

import { prefers24HourClock } from './dates'

function subscribe(onChange: () => void): () => void {
    const subscription = AppState.addEventListener('change', (state) => {
        if (state === 'active') {
            onChange()
        }
    })
    return () => subscription.remove()
}

export function useClockPreference(): boolean {
    return useSyncExternalStore(subscribe, prefers24HourClock)
}
