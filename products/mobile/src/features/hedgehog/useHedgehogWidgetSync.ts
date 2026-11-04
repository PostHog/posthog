import AsyncStorage from '@react-native-async-storage/async-storage'
import { useEffect } from 'react'
import { AppState } from 'react-native'

import { track } from '@/lib/analytics'

// Local Expo modules have no node_modules entry, so they are imported by path.
import { isAvailable, setChoreography } from '../../../modules/hedgehog-widget'

import { createChoreography, dailySeed } from './choreography'

const SEED_KEY = 'hedgehog_widget_seed'
// Stored with the seed. Bump it when createChoreography writes a different script, so that a device that synced
// today with the old app writes the new script after the update instead of the next day.
const SCRIPT_REVISION = 5

let inFlight: Promise<void> | null = null

/**
 * Hands today's choreography to the widget once per UTC day. Each write makes the OS reload every placed widget,
 * and iOS budgets those reloads, so a foreground on the same day must not write again.
 */
export function syncHedgehogWidget(now: Date): Promise<void> {
    // Launch and the first AppState change can fire together. Share one run so both do not read the old seed.
    inFlight ??= runSync(now).finally(() => {
        inFlight = null
    })
    return inFlight
}

async function runSync(now: Date): Promise<void> {
    try {
        if (!isAvailable()) {
            return
        }
        const seed = dailySeed(now)
        const stamp = `${SCRIPT_REVISION}:${seed}`
        if ((await AsyncStorage.getItem(SEED_KEY)) === stamp) {
            return
        }
        const startsAt = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()))
        setChoreography(JSON.stringify(createChoreography({ seed, startsAt, generatedAt: now })))
        await AsyncStorage.setItem(SEED_KEY, stamp)
        track('mobile_hedgehog_widget_synced', { seed })
    } catch {
        // The widget keeps its last script or its built-in routine, so a failed sync must not reach the app.
    }
}

export function useHedgehogWidgetSync(): void {
    useEffect(() => {
        if (!isAvailable()) {
            return
        }
        void syncHedgehogWidget(new Date())
        const subscription = AppState.addEventListener('change', (next) => {
            if (next === 'active') {
                void syncHedgehogWidget(new Date())
            }
        })
        return () => subscription.remove()
    }, [])
}
