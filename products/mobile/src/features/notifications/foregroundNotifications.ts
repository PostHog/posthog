import type { Notification, NotificationBehavior } from 'expo-notifications'
import { AppState } from 'react-native'

import { queryClient } from '@/api/queryClient'
import { reportKeys, type SignalReportApi } from '@/api/reports'
import type { TaskApi } from '@/api/tasks'
import { useAuthStore } from '@/auth/authStore'
import { track } from '@/lib/analytics'
import { asRecord } from '@/lib/records'

import { snoozeKey } from '../snooze/snoozeEntries'
import { useSnoozeStore } from '../snooze/snoozeStore'
import { NotificationPresentation } from './notificationPresentation'
import { notificationKind, notificationTarget } from './notificationRouting'

interface ViewedReport {
    accountKey: string
    projectId: number
    reportId: string
}

let viewedReport: ViewedReport | null = null
let viewedTask: { accountKey: string; projectId: number; taskId: string } | null = null

export function setViewedNotificationTask(task: typeof viewedTask): void {
    viewedTask = task
}

export function isViewedNotificationTask(task: NonNullable<typeof viewedTask>): boolean {
    return (
        viewedTask?.accountKey === task.accountKey &&
        viewedTask.projectId === task.projectId &&
        viewedTask.taskId === task.taskId
    )
}
const presentation = new NotificationPresentation()

export function setViewedNotificationReport(report: ViewedReport | null): void {
    viewedReport = report
}

function behavior(show: boolean): NotificationBehavior {
    return { shouldShowBanner: show, shouldShowList: show, shouldPlaySound: false, shouldSetBadge: false }
}

function shouldShowWhileActive(data: unknown, host: string, accountKey: string): boolean {
    const target = notificationTarget(data)
    // Legacy task pushes lack a project. Without it, a cached association cannot safely mute a push.
    if (!target || target.projectId === null) {
        return true
    }
    if (
        target.type === 'task' &&
        isViewedNotificationTask({ accountKey, projectId: target.projectId, taskId: target.id })
    ) {
        return false
    }
    if (target.type === 'task' && asRecord(data)?.type === 'task') {
        return true
    }
    const scope = { host, projectId: target.projectId }
    const active =
        viewedReport?.accountKey === accountKey && viewedReport.projectId === target.projectId ? viewedReport : null
    let reportId = target.type === 'report' ? target.id : null
    if (target.type === 'task') {
        reportId = queryClient.getQueryData<TaskApi>(reportKeys.task(scope, target.id))?.signal_report ?? null
        if (!reportId && active) {
            const report = queryClient.getQueryData<SignalReportApi>(reportKeys.detail(scope, active.reportId))
            if (report?.assignee?.task_id === target.id) {
                reportId = active.reportId
            }
        }
    }
    if (!reportId) {
        return true
    }
    if (active?.reportId === reportId) {
        return false
    }
    const snooze = useSnoozeStore.getState().entries[snoozeKey(scope, reportId)]
    // Signal snoozes are labels, not authoritative state: the server may already have woken the report.
    const snoozed = snooze?.kind === 'until' && new Date(snooze.until).getTime() > Date.now()
    return !snoozed
}

/** Stay synchronous: Expo has a short handler deadline, so never fetch a task to decide whether to interrupt. */
export function foregroundNotificationBehavior(notification: Notification): NotificationBehavior {
    if (AppState.currentState !== 'active') {
        return behavior(true)
    }
    const auth = useAuthStore.getState()
    if (auth.status !== 'signed_in' || !auth.host || !auth.user) {
        return behavior(false)
    }
    const host = auth.host.replace(/\/$/, '')
    const accountKey = `${host}|${auth.user.uuid}`
    const data = notification.request.content.data
    const firstDelivery = presentation.shouldPresent(notification.request.identifier, data, accountKey, Date.now())
    if (!firstDelivery) {
        return behavior(false)
    }
    const shown = shouldShowWhileActive(data, host, accountKey)
    track('mobile_push_received', { kind: notificationKind(data), shown })
    return behavior(shown)
}
