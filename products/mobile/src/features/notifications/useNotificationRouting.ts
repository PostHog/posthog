import * as Notifications from 'expo-notifications'
import { router, usePathname, useRootNavigationState } from 'expo-router'
import { useEffect } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'

import { setViewedNotificationReport } from './foregroundNotifications'
import { notificationKind, resolveNotificationRoute } from './notificationRouting'
import { notificationsSupported } from './pushSupport'
import { findTask } from './taskLookup'

/** A cold-start tap can arrive both as the last response and through the listener. */
const handled = new Set<string>()

async function openFromNotification(response: Notifications.NotificationResponse): Promise<void> {
    const auth = useAuthStore.getState()
    if (auth.status !== 'signed_in') {
        return
    }
    const id = response.notification.request.identifier
    if (handled.has(id)) {
        return
    }
    handled.add(id)
    Notifications.clearLastNotificationResponse()
    const data: unknown = response.notification.request.content.data
    track('mobile_push_opened', { kind: notificationKind(data) })
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
        track('mobile_demo_ended', { from: 'push' })
        useDemoMode.getState().setEnabled(false)
    }
    if (route.switchToProjectId !== null) {
        useAuthStore.getState().selectProject(route.switchToProjectId, 'push')
    }
    if (route.pathname === '/inbox') {
        router.navigate('/inbox')
    } else {
        router.push(`${route.pathname}?from=push`)
    }
}

// Waits until the navigator is mounted and the session has loaded, because the route depends on the user's projects.
export function useNotificationRouting(): void {
    const navigationReady = Boolean(useRootNavigationState()?.key)
    const signedIn = useAuthStore((state) => state.status === 'signed_in')
    const host = useAuthStore((state) => state.host)
    const userUuid = useAuthStore((state) => state.user?.uuid)
    const projectId = useAuthStore((state) => state.projectId)
    const pathname = usePathname()

    useEffect(() => {
        const reportId = /^\/report\/([^/]+)$/.exec(pathname)?.[1]
        setViewedNotificationReport(
            signedIn && host && userUuid && projectId !== null && reportId
                ? { accountKey: `${host.replace(/\/$/, '')}|${userUuid}`, projectId, reportId }
                : null
        )
        return () => setViewedNotificationReport(null)
    }, [signedIn, host, userUuid, projectId, pathname])

    useEffect(() => {
        if (!navigationReady || !signedIn || !notificationsSupported()) {
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
    }, [navigationReady, signedIn])
}
