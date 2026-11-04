import { requireOptionalNativeModule } from 'expo-modules-core'

export interface WidgetCredentials {
    host: string
    projectId: number
    projectName: string
    accessToken: string
    /** Epoch ms, or null when the token does not expire. */
    expiresAt: number | null
    userUuid: string
}

interface ChartWidgetNativeModule {
    setCredentials(json: string): void
    clearCredentials(): void
    setCatalog(json: string): void
    clearCatalog(): void
    reloadWidgets(): void
}

const native = requireOptionalNativeModule<ChartWidgetNativeModule>('ChartWidget')

/** False on web and in any build without the native module, so callers can skip the sync. */
export function isAvailable(): boolean {
    return native !== null
}

/** Stores a read-only copy of the session for the widget's own reads, then refreshes every placed widget. */
export function setCredentials(credentials: WidgetCredentials): void {
    native?.setCredentials(JSON.stringify({ version: 1, ...credentials }))
}

/** Removes the stored session and every cached snapshot; widgets then ask to sign in. */
export function clearCredentials(): void {
    native?.clearCredentials()
}

/** Replaces the pin catalog the OS pickers list, then refreshes every placed widget. */
export function setCatalog(json: string): void {
    native?.setCatalog(json)
}

export function clearCatalog(): void {
    native?.clearCatalog()
}

export function reloadWidgets(): void {
    native?.reloadWidgets()
}
