import { requireOptionalNativeModule } from 'expo-modules-core'

export interface NotificationTap {
    identifier: string
    data: unknown
}

interface NotificationIntentsNativeModule {
    getPending(): { identifier: string; data: string } | null
    acknowledge(identifier: string): void
}

const native = requireOptionalNativeModule<NotificationIntentsNativeModule>('NotificationIntents')

export function getPendingNotificationTap(): NotificationTap | null | undefined {
    if (!native) {
        return undefined
    }
    const pending = native.getPending()
    return pending ? { identifier: pending.identifier, data: JSON.parse(pending.data) } : null
}

export function acknowledgeNotificationTap(identifier: string): void {
    native?.acknowledge(identifier)
}
