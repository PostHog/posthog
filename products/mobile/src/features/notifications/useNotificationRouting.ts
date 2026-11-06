import * as Notifications from 'expo-notifications'
import { router, useNavigationContainerRef, usePathname, useRootNavigationState } from 'expo-router'
import { useEffect } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { withAppReloadBlocked } from '@/lib/appReload'

import { isViewedNotificationTask, setViewedNotificationReport } from './foregroundNotifications'
import { acknowledgeNotificationTap, getPendingNotificationTap, type NotificationTap } from './notificationIntents'
import { notificationKind, notificationTarget, resolveNotificationRoute } from './notificationRouting'
import { notificationsSupported } from './pushSupport'
import { findTask } from './taskLookup'

/** A cold-start tap can arrive both as the last response and through the listener. */
const handled = new Set<string>()
const inFlight = new Set<string>()

function finishNotificationTap(identifier: string): void {
    acknowledgeNotificationTap(identifier)
    handled.add(identifier)
    if (Notifications.getLastNotificationResponse()?.notification.request.identifier === identifier) {
        Notifications.clearLastNotificationResponse()
    }
}

async function openFromNotification(tap: NotificationTap, isChatOpen: () => boolean): Promise<void> {
    const auth = useAuthStore.getState()
    if (auth.status !== 'signed_in') {
        return
    }
    const id = tap.identifier
    if (handled.has(id)) {
        acknowledgeNotificationTap(id)
        return
    }
    if (inFlight.has(id)) {
        return
    }
    inFlight.add(id)
    try {
        const data = tap.data
        track('mobile_push_opened', { kind: notificationKind(data) })
        const route = await resolveNotificationRoute(data, {
            currentProjectId: auth.projectId,
            projectIds: auth.projects.map((project) => project.id),
            findTask,
        })
        const currentAuth = useAuthStore.getState()
        const pending = getPendingNotificationTap()
        if (
            (pending !== undefined && pending?.identifier !== id) ||
            currentAuth.status !== 'signed_in' ||
            currentAuth.host !== auth.host ||
            currentAuth.user?.uuid !== auth.user?.uuid
        ) {
            return
        }
        if (!route) {
            finishNotificationTap(id)
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
            finishNotificationTap(id)
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
        finishNotificationTap(id)
    } finally {
        inFlight.delete(id)
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
        const open = (tap: NotificationTap): void => {
            void withAppReloadBlocked(() =>
                openFromNotification(tap, () => navigation.getCurrentRoute()?.name === 'chat')
            ).catch(() => undefined)
        }
        const fromResponse = (response?: Notifications.NotificationResponse): void => {
            const pending = getPendingNotificationTap()
            if (pending !== undefined) {
                if (pending) {
                    open(pending)
                }
            } else if (response) {
                open({
                    identifier: response.notification.request.identifier,
                    data: response.notification.request.content.data,
                })
            }
        }
        fromResponse(Notifications.getLastNotificationResponse() ?? undefined)
        const subscription = Notifications.addNotificationResponseReceivedListener(fromResponse)
        return () => subscription.remove()
    }, [navigationReady, signedIn, navigation])
}
