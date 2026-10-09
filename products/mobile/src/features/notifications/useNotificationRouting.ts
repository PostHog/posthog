import * as Notifications from 'expo-notifications'
import { router, useRootNavigationState } from 'expo-router'
import { useEffect } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'

import { notificationKind, resolveNotificationRoute } from './notificationRouting'
import { notificationsSupported } from './pushSupport'
import { findTask } from './taskLookup'

/** A cold-start tap can arrive both as the last response and through the listener. */
const handled = new Set<string>()

async function openFromNotification(response: Notifications.NotificationResponse): Promise<void> {
    const id = response.notification.request.identifier
    if (handled.has(id)) {
        return
    }
    handled.add(id)
    Notifications.clearLastNotificationResponse()
    const data: unknown = response.notification.request.content.data
    track('mobile_push_opened', { kind: notificationKind(data) })
    const auth = useAuthStore.getState()
    if (auth.status !== 'signed_in') {
        return
    }
    const route = await resolveNotificationRoute(data, {
        currentProjectId: auth.projectId,
        projectIds: auth.projects.map((project) => project.id),
        findTask,
    })
    if (!route) {
        return
    }
    // A push is about live data, which demo mode would hide behind fixtures.
    if (useDemoMode.getState().enabled) {
        useDemoMode.getState().setEnabled(false)
    }
    if (route.switchToProjectId !== null) {
        useAuthStore.getState().selectProject(route.switchToProjectId)
    }
    if (route.pathname === '/inbox') {
        router.navigate('/inbox')
    } else {
        router.push(route.pathname)
    }
}

// Waits until the navigator is mounted and the session has loaded, because the route depends on the user's projects.
export function useNotificationRouting(): void {
    const navigationReady = Boolean(useRootNavigationState()?.key)
    const sessionLoaded = useAuthStore((state) => state.status !== 'loading')

    useEffect(() => {
        if (!navigationReady || !sessionLoaded || !notificationsSupported()) {
            return
        }
        const open = (response: Notifications.NotificationResponse): void => {
            openFromNotification(response).catch(() => undefined)
        }
        const last = Notifications.getLastNotificationResponse()
        if (last) {
            open(last)
        }
        const subscription = Notifications.addNotificationResponseReceivedListener(open)
        return () => subscription.remove()
    }, [navigationReady, sessionLoaded])
}
