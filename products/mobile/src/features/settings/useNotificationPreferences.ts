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
import { useDataMode } from '@/demo/demoMode'
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
        setSaveError(null)
        if (mode === 'demo') {
            setDemoPreferences((current) => ({ ...current, [key]: enabled }))
            return
        }
        try {
            const preferences = await setNotificationPreference(key, enabled)
            queryClient.setQueryData(queryKey, preferences)
        } catch {
            setSaveError("Couldn't save notification preferences. Try again.")
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
