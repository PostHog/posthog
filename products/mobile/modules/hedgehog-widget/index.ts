import { requireOptionalNativeModule } from 'expo-modules-core'

interface HedgehogWidgetNativeModule {
    setChoreography(json: string): void
    clearChoreography(): void
}

const native = requireOptionalNativeModule<HedgehogWidgetNativeModule>('HedgehogWidget')

/** False on web and in any build without the native module, so callers can skip the sync. */
export function isAvailable(): boolean {
    return native !== null
}

/** Persists the choreography JSON where the widget reads it and refreshes every placed widget. */
export function setChoreography(json: string): void {
    native?.setChoreography(json)
}

/** Removes the stored choreography; widgets then play their built-in fallback. */
export function clearChoreography(): void {
    native?.clearChoreography()
}
