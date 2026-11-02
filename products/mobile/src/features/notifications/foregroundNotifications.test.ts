import * as Notifications from 'expo-notifications'
import { AppState } from 'react-native'

import { queryClient } from '@/api/queryClient'
import { reportKeys } from '@/api/reports'
import { useAuthStore } from '@/auth/authStore'
import { useSnoozeStore } from '../snooze/snoozeStore'
import { setViewedNotificationReport, setViewedNotificationTask } from './foregroundNotifications'
import { configureNotifications } from './pushRegistration'

jest.mock('expo-notifications', () => ({ setNotificationHandler: jest.fn() }))
jest.mock('expo-constants', () => ({ __esModule: true, default: {} }))
jest.mock('@/api/pushTokens', () => ({}))
jest.mock('@/auth/authStore', () => ({ useAuthStore: { getState: jest.fn() } }))
jest.mock('../snooze/snoozeStore', () => ({ useSnoozeStore: { getState: jest.fn() } }))
jest.mock('./pushStore', () => ({}))
jest.mock('./pushSupport', () => ({ notificationsSupported: () => true }))

const SCOPE = { host: 'https://app.example.com', projectId: 2 }
const REPORT = { type: 'report', report_id: 'report-1', project_id: 2, notificationKind: 'report_visible' }
const TASK = { taskId: 'task-1', taskRunId: 'run-1', projectId: 2, notificationKind: 'completed' }
let accountNumber = 0
let identifier = 0

function viewReport(): void {
    setViewedNotificationReport({
        accountKey: `${SCOPE.host}|user-${accountNumber}`,
        projectId: 2,
        reportId: 'report-1',
    })
}

async function deliver(data: Record<string, unknown>): Promise<Notifications.NotificationBehavior> {
    const handler = jest.mocked(Notifications.setNotificationHandler).mock.calls[0]?.[0]
    if (!handler) {
        throw new Error('Notification handler was not registered')
    }
    return handler.handleNotification({
        date: Date.now(),
        request: {
            identifier: `push-${identifier++}`,
            trigger: { type: 'push' },
            content: {
                title: 'PostHog',
                subtitle: null,
                body: 'Report update',
                data,
                categoryIdentifier: null,
                sound: null,
            },
        },
    })
}

beforeEach(() => {
    accountNumber++
    AppState.currentState = 'active'
    jest.mocked(useAuthStore.getState).mockReturnValue({
        status: 'signed_in',
        host: SCOPE.host,
        user: { uuid: `user-${accountNumber}` },
    } as ReturnType<typeof useAuthStore.getState>)
    jest.mocked(useSnoozeStore.getState).mockReturnValue({ entries: {} } as ReturnType<typeof useSnoozeStore.getState>)
    queryClient.setDefaultOptions({ queries: { gcTime: Infinity } })
    queryClient.clear()
    setViewedNotificationReport(null)
    setViewedNotificationTask(null)
    jest.mocked(Notifications.setNotificationHandler).mockClear()
    configureNotifications()
})

afterEach(() => queryClient.clear())

test.each([REPORT, TASK])('does not interrupt the report already being viewed: %j', async (data) => {
    viewReport()
    queryClient.setQueryData(reportKeys.task(SCOPE, 'task-1'), { signal_report: 'report-1' })
    await expect(deliver(data)).resolves.toEqual({
        shouldShowBanner: false,
        shouldShowList: false,
        shouldPlaySound: false,
        shouldSetBadge: false,
    })
})

test('recognizes the active report assignee before the task request has loaded', async () => {
    viewReport()
    queryClient.setQueryData(reportKeys.detail(SCOPE, 'report-1'), { assignee: { task_id: 'task-1' } })
    await expect(deliver(TASK)).resolves.toMatchObject({ shouldShowBanner: false })
})

test.each([
    ['another report', { ...REPORT, report_id: 'report-2' }],
    ['another project', { ...REPORT, project_id: 3 }],
    ['an uncached task', TASK],
    ['a legacy payload', { ...REPORT, project_id: undefined }],
])('still presents a notification for %s', async (_name, data) => {
    viewReport()
    await expect(deliver(data)).resolves.toMatchObject({ shouldShowBanner: true, shouldShowList: true })
})

test.each([REPORT, TASK])('mutes a locally time-snoozed report in the foreground: %j', async (data) => {
    queryClient.setQueryData(reportKeys.task(SCOPE, 'task-1'), { signal_report: 'report-1' })
    jest.mocked(useSnoozeStore.getState).mockReturnValue({
        entries: {
            [`${SCOPE.host}|2|report-1`]: {
                kind: 'until',
                at: new Date().toISOString(),
                until: new Date(Date.now() + 60_000).toISOString(),
            },
        },
    } as ReturnType<typeof useSnoozeStore.getState>)
    await expect(deliver(data)).resolves.toMatchObject({ shouldShowBanner: false, shouldShowList: false })
})

test.each(['expired', 'signals'])('allows a reminder or new activity after a %s snooze', async (kind) => {
    const at = new Date(Date.now() - 60_000).toISOString()
    jest.mocked(useSnoozeStore.getState).mockReturnValue({
        entries: {
            [`${SCOPE.host}|2|report-1`]:
                kind === 'signals' ? { kind, at, threshold: 10 } : { kind: 'until', at, until: at },
        },
    } as ReturnType<typeof useSnoozeStore.getState>)
    await expect(deliver(REPORT)).resolves.toMatchObject({ shouldShowBanner: true })
})

test('the registered handler collapses repeated terminal outcomes with different push identifiers', async () => {
    const results = await Promise.all([deliver(TASK), deliver(TASK), deliver(TASK), deliver(TASK)])
    expect(results.map((result) => result.shouldShowBanner)).toEqual([true, false, false, false])
})

test('does not apply a stale viewed report to a different account', async () => {
    setViewedNotificationReport({ accountKey: `${SCOPE.host}|previous-user`, projectId: 2, reportId: 'report-1' })
    await expect(deliver(REPORT)).resolves.toMatchObject({ shouldShowBanner: true })
})

test('does not display account notifications while signed out', async () => {
    jest.mocked(useAuthStore.getState).mockReturnValue({ status: 'signed_out' } as ReturnType<
        typeof useAuthStore.getState
    >)
    await expect(deliver(REPORT)).resolves.toMatchObject({ shouldShowBanner: false })
})

test('does not treat a backgrounded report as being watched', async () => {
    viewReport()
    AppState.currentState = 'background'
    await expect(deliver(REPORT)).resolves.toMatchObject({ shouldShowBanner: true })
})

test.each([TASK, { ...TASK, type: 'task' }])('does not interrupt the task already open in a chat: %j', async (data) => {
    setViewedNotificationTask({ accountKey: `${SCOPE.host}|user-${accountNumber}`, projectId: 2, taskId: 'task-1' })
    await expect(deliver(data)).resolves.toMatchObject({ shouldShowBanner: false })
    setViewedNotificationTask(null)
    await expect(deliver({ ...data, taskRunId: 'later-run' })).resolves.toMatchObject({ shouldShowBanner: true })
})

test('an explicit discussion task interrupts a viewed report, while a legacy report-linked task does not', async () => {
    viewReport()
    queryClient.setQueryData(reportKeys.task(SCOPE, 'task-1'), { signal_report: 'report-1' })
    await expect(deliver({ ...TASK, type: 'task' })).resolves.toMatchObject({ shouldShowBanner: true })
    await expect(deliver({ ...TASK, taskRunId: 'legacy-run' })).resolves.toMatchObject({ shouldShowBanner: false })
})
