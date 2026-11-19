import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { AppState } from 'react-native'

import { getNotificationPreferences } from '@/api/notificationPreferences'
import { useAuthStore } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { useDemoMode } from '@/demo/demoMode'
import { captureError } from '@/lib/analytics'

import { cancelScheduledSnoozeReminders, snoozeRemindersEnabled } from './reminders'

export function useSnoozeReminderPreferences(): void {
    const host = useAuthStore((state) => state.host)
    const userId = useAuthStore((state) => state.user?.uuid)
    const signedIn = useAuthStore((state) => state.signedIn)
    const demo = useDemoMode((state) => state.enabled)
    const client = useQueryClient()
    const enabled = signedIn && !demo && Boolean(host && userId)
    const { data, dataUpdatedAt } = useQuery({
        queryKey: ['mobile-notification-preferences', host, userId],
        queryFn: ({ signal }) => getNotificationPreferences(signal),
        enabled,
        staleTime: 30_000,
    })
    useEffect(() => {
        if (enabled && dataUpdatedAt > 0 && data && !snoozeRemindersEnabled(data)) {
            const generation = sessionGeneration()
            void cancelScheduledSnoozeReminders(() => generation === sessionGeneration()).catch(captureError)
        }
    }, [enabled, data, dataUpdatedAt])
    useEffect(() => {
        if (!enabled) {
            return
        }
        const subscription = AppState.addEventListener('change', (state) => {
            if (state === 'active') {
                void client.invalidateQueries({ queryKey: ['mobile-notification-preferences', host, userId] })
            }
        })
        return () => subscription.remove()
    }, [enabled, host, userId, client])
}
