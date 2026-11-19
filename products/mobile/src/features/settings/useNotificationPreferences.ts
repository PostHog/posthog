import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
    DEFAULT_NOTIFICATION_PREFERENCES,
    getNotificationPreferences,
    type NotificationPreferenceKey,
    type NotificationPreferences,
    setNotificationPreference,
} from '@/api/notificationPreferences'
import { useAuthStore } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { useDataMode } from '@/demo/demoMode'
import { cancelScheduledSnoozeReminders, snoozeRemindersEnabled } from '@/features/snooze/reminders'
import { track } from '@/lib/analytics'
import { useAsyncAction } from '@/lib/useAsyncAction'

export function useNotificationPreferences(): {
    preferences: NotificationPreferences | undefined
    loading: boolean
    loadError: boolean
    saveError: string | null
    saving: boolean
    retry: () => void
    change: (key: NotificationPreferenceKey, enabled: boolean) => Promise<void>
} {
    const mode = useDataMode()
    const signedIn = useAuthStore((state) => state.signedIn)
    const host = useAuthStore((state) => state.host)
    const userId = useAuthStore((state) => state.user?.uuid)
    const queryClient = useQueryClient()
    const queryKey = ['mobile-notification-preferences', host, userId]
    const [demoPreferences, setDemoPreferences] = useState(DEFAULT_NOTIFICATION_PREFERENCES)
    const [saveError, setSaveError] = useState<string | null>(null)
    const query = useQuery({
        queryKey,
        queryFn: ({ signal }) => getNotificationPreferences(signal),
        enabled: mode === 'live' && signedIn && Boolean(host && userId),
        retry: false,
    })
    const save = useAsyncAction(async (key: NotificationPreferenceKey, enabled: boolean) => {
        const generation = sessionGeneration()
        const isCurrent = (): boolean => generation === sessionGeneration()
        setSaveError(null)
        const previousValue = (mode === 'demo' ? demoPreferences : query.data)?.[key]
        if (mode === 'demo') {
            setDemoPreferences((current) => ({ ...current, [key]: enabled }))
            track('mobile_notification_preference_changed', {
                preference: key,
                previous_value: previousValue,
                enabled,
                demo: true,
            })
            return
        }
        try {
            const preferences = await setNotificationPreference(key, enabled)
            if (!isCurrent()) {
                return
            }
            queryClient.setQueryData(queryKey, preferences)
            track('mobile_notification_preference_changed', { preference: key, previous_value: previousValue, enabled })
            if (!snoozeRemindersEnabled(preferences)) {
                try {
                    await cancelScheduledSnoozeReminders(isCurrent)
                } catch {
                    if (!isCurrent()) {
                        return
                    }
                    setSaveError(
                        "Settings saved, but reminders couldn't be canceled. Reopen the app to retry, or turn off notifications in system settings."
                    )
                    track('mobile_notification_preference_failed', {
                        preference: key,
                        enabled,
                        reason: 'reminder_cleanup',
                    })
                }
            }
        } catch {
            if (!isCurrent()) {
                return
            }
            track('mobile_notification_preference_failed', { preference: key, enabled, reason: 'save' })
            setSaveError("Couldn't save your settings. Try again.")
        }
    })
    return {
        preferences: mode === 'demo' ? demoPreferences : query.data,
        loading: mode === 'loading' || (mode === 'live' && query.isPending),
        loadError: mode === 'live' && query.isError,
        saveError,
        saving: save.pending,
        retry: () => void query.refetch(),
        change: save.run,
    }
}
