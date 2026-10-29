import * as Notifications from 'expo-notifications'
import { router, useNavigationContainerRef, usePathname, useRootNavigationState } from 'expo-router'
import { useEffect } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { withAppReloadBlocked } from '@/lib/appReload'

import { isViewedNotificationTask, setViewedNotificationReport } from './foregroundNotifications'
import { notificationKind, notificationTarget, resolveNotificationRoute } from './notificationRouting'
import { notificationsSupported } from './pushSupport'
import { findTask } from './taskLookup'

/** A cold-start tap can arrive both as the last response and through the listener. */
const handled = new Set<string>()

async function openFromNotification(
    response: Notifications.NotificationResponse,
    isChatOpen: () => boolean
): Promise<void> {
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
    const currentAuth = useAuthStore.getState()
    if (
        currentAuth.status !== 'signed_in' ||
        currentAuth.host !== auth.host ||
        currentAuth.user?.uuid !== auth.user?.uuid
    ) {
        return
    }
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
    const target = notificationTarget(data)
    const chatOpen = isChatOpen()
    const isChatRoute = route.pathname.startsWith('/chat?')
    const projectId = route.switchToProjectId ?? auth.projectId
    // Creating a task or tapping New chat changes the live session without changing the route's taskId.
    if (
        chatOpen &&
        isChatRoute &&
        target?.type === 'task' &&
        auth.host &&
        auth.user &&
        projectId !== null &&
        isViewedNotificationTask({
            accountKey: `${auth.host.replace(/\/$/, '')}|${auth.user.uuid}`,
            projectId,
            taskId: target.id,
        })
    ) {
        return
    }
    if (route.pathname === '/inbox') {
        router.navigate('/inbox')
    } else {
        const href = `${route.pathname}${route.pathname.includes('?') ? '&' : '?'}from=push`
        if (chatOpen && isChatRoute) {
            router.replace(href)
        } else {
            router.push(href)
        }
    }
}

// Waits until the navigator is mounted and the session has loaded, because the route depends on the user's projects.
export function useNotificationRouting(): void {
    const navigation: { getCurrentRoute: () => { name: string } | undefined } = useNavigationContainerRef()
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
            void withAppReloadBlocked(() =>
                openFromNotification(response, () => navigation.getCurrentRoute()?.name === 'chat')
            ).catch(() => undefined)
        }
        const last = Notifications.getLastNotificationResponse()
        if (last) {
            open(last)
        }
        const subscription = Notifications.addNotificationResponseReceivedListener(open)
        return () => subscription.remove()
    }, [navigationReady, signedIn, navigation])
}
