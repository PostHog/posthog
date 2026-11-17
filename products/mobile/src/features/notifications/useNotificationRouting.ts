import * as Notifications from 'expo-notifications'
import {
    router,
    useGlobalSearchParams,
    useNavigationContainerRef,
    usePathname,
    useRootNavigationState,
} from 'expo-router'
import { useEffect, useState } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { reportLinkFromParams, useReportLinkScope } from '@/features/report/reportLinkScope'
import { reminderAccount } from '@/features/snooze/reminders'
import { track } from '@/lib/analytics'
import { withAppReloadBlocked } from '@/lib/appReload'

import { isViewedNotificationTask, setViewedNotificationReport } from './foregroundNotifications'
import { acknowledgeNotificationTap, getPendingNotificationTap, type NotificationTap } from './notificationIntents'
import {
    type NotificationRoute,
    notificationKind,
    notificationTarget,
    resolveNotificationRoute,
} from './notificationRouting'
import { notificationsSupported } from './pushSupport'
import { findTask } from './taskLookup'

/**
 * A cold-start tap can arrive both as the last response and through the listener. It outlives account switches,
 * because Expo keeps the last response in memory and the next account's routing reads it again.
 */
const handled = new Set<string>()
// Keyed by account too, so a tap that an account switch interrupted is judged again against the account after it.
const inFlight = new Set<string>()
/** Reminder taps that already started a switch to their account, so a later judgment never switches again. */
const accountSwitches = new Set<string>()

const INBOX: NotificationRoute = { pathname: '/inbox', switchToProjectId: null }

/** `switched`: the tap moved to its reminder's account first. `unavailable`: its account could not open it. */
type TapAccount = 'switched' | 'unavailable'

function finishNotificationTap(identifier: string, data: unknown, account?: TapAccount): void {
    track('mobile_push_opened', { kind: notificationKind(data), ...(account ? { account } : {}) })
    acknowledgeNotificationTap(identifier)
    handled.add(identifier)
    if (Notifications.getLastNotificationResponse()?.notification.request.identifier === identifier) {
        Notifications.clearLastNotificationResponse()
    }
}

/**
 * A remote push names no account, so it opens in the active one, where the server refuses data of another account. A
 * snooze reminder is the app's own, so it opens in the account that scheduled it. Returns false when the tap waits for
 * the next session.
 */
async function openInReminderAccount(tap: NotificationTap, account: string): Promise<boolean> {
    const auth = useAuthStore.getState()
    const target = auth.accounts.find((candidate) => candidate.key === account)
    if (!target || target.needsSignIn || accountSwitches.has(tap.identifier)) {
        return true
    }
    accountSwitches.add(tap.identifier)
    try {
        await auth.switchAccount(account, {
            projectId: notificationTarget(tap.data)?.projectId ?? undefined,
            from: 'push',
        })
        // The new account's screens mount next, and the routing hook judges this tap again there.
        return false
    } catch {
        // The switch did not happen, so the tap falls back to the active account's inbox.
        return true
    }
}

async function openFromNotification(
    tap: NotificationTap,
    isChatOpen: () => boolean,
    coldStart: boolean
): Promise<void> {
    const auth = useAuthStore.getState()
    if (auth.status !== 'signed_in') {
        return
    }
    const id = tap.identifier
    if (handled.has(id)) {
        acknowledgeNotificationTap(id)
        return
    }
    const attempt = `${auth.activeAccountKey}|${id}`
    if (inFlight.has(attempt)) {
        return
    }
    inFlight.add(attempt)
    try {
        const data = tap.data
        const isCurrent = (): boolean => {
            const currentAuth = useAuthStore.getState()
            const pending = getPendingNotificationTap()
            return (
                (pending === undefined || pending?.identifier === id) &&
                !handled.has(id) &&
                currentAuth.status === 'signed_in' &&
                currentAuth.host === auth.host &&
                currentAuth.user?.uuid === auth.user?.uuid
            )
        }
        const owner = await reminderAccount(id)
        if (owner.kind === 'account' && owner.key !== auth.activeAccountKey) {
            if ((await openInReminderAccount(tap, owner.key)) && isCurrent()) {
                router.navigate('/inbox')
                finishNotificationTap(id, data, 'unavailable')
            }
            return
        }
        const route =
            owner.kind === 'removed'
                ? INBOX
                : await resolveNotificationRoute(data, {
                      currentProjectId: auth.projectId,
                      projectIds: auth.projects.map((project) => project.id),
                      findTask,
                  })
        if (!isCurrent()) {
            return
        }
        const account: TapAccount | undefined =
            owner.kind === 'removed' ? 'unavailable' : accountSwitches.has(id) ? 'switched' : undefined
        if (!route) {
            finishNotificationTap(id, data, account)
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
            finishNotificationTap(id, data, account)
            return
        }
        if (route.pathname === '/inbox') {
            router.navigate('/inbox')
        } else {
            const href = `${route.pathname}${route.pathname.includes('?') ? '&' : '?'}from=push`
            if (chatOpen && isChatRoute) {
                router.replace(href)
            } else {
                // A cold start lands on Home, so a report opens above the inbox it belongs to and Back returns there.
                if (coldStart && route.pathname.startsWith('/report/')) {
                    router.navigate('/inbox')
                }
                router.push(href)
            }
        }
        finishNotificationTap(id, data, account)
    } finally {
        inFlight.delete(attempt)
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
    const accountKey = useAuthStore((state) => state.activeAccountKey)
    // The root layout keeps the stack unmounted for one commit after another account becomes active. Taps wait for
    // that commit too, so they never navigate a stack that is about to be replaced.
    const [screensAccount, setScreensAccount] = useState(accountKey)
    const accountChanged = accountKey !== null && screensAccount !== null && accountKey !== screensAccount
    const pathname = usePathname()
    const params = useGlobalSearchParams()
    const linkScope = useReportLinkScope(reportLinkFromParams(params))
    // A link can open a report in another project, and a push for it names that project, not the session's.
    const viewedProjectId = linkScope.kind === 'scope' ? (linkScope.override?.projectId ?? projectId) : null

    useEffect(() => {
        if (accountKey !== null && accountKey !== screensAccount) {
            setScreensAccount(accountKey)
        }
    }, [accountKey, screensAccount])

    useEffect(() => {
        const reportId = /^\/report\/([^/]+)$/.exec(pathname)?.[1]
        setViewedNotificationReport(
            signedIn && host && userUuid && viewedProjectId !== null && reportId
                ? { accountKey: `${host.replace(/\/$/, '')}|${userUuid}`, projectId: viewedProjectId, reportId }
                : null
        )
        return () => setViewedNotificationReport(null)
    }, [signedIn, host, userUuid, viewedProjectId, pathname])

    useEffect(() => {
        if (!navigationReady || !signedIn || accountChanged || !notificationsSupported()) {
            return
        }
        const open = (tap: NotificationTap, coldStart: boolean): void => {
            void withAppReloadBlocked(() =>
                openFromNotification(tap, () => navigation.getCurrentRoute()?.name === 'chat', coldStart)
            ).catch(() => undefined)
        }
        const fromResponse = (response: Notifications.NotificationResponse | undefined, coldStart: boolean): void => {
            const pending = getPendingNotificationTap()
            if (pending !== undefined) {
                if (pending) {
                    open(pending, coldStart)
                }
            } else if (response) {
                open(
                    {
                        identifier: response.notification.request.identifier,
                        data: response.notification.request.content.data,
                    },
                    coldStart
                )
            }
        }
        // The tap that launched the app, or one that waited for sign-in or an account switch, is read here; later taps
        // arrive through the listener while the person is already on a screen.
        fromResponse(Notifications.getLastNotificationResponse() ?? undefined, true)
        const subscription = Notifications.addNotificationResponseReceivedListener((response) =>
            fromResponse(response, false)
        )
        return () => subscription.remove()
    }, [navigationReady, signedIn, accountChanged, navigation])
}
