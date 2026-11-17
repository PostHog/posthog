import { type InfiniteData, type QueryClient, useQueryClient } from '@tanstack/react-query'

import { NotSignedInError } from '@/api/client'
import {
    type InboxPageApi,
    type ProjectScope,
    reportKeys,
    type SignalReportApi,
    snoozeReportForSignals,
} from '@/api/reports'
import { addAccountRemovedTask, addSessionEndTask, launchAccount, useAuthStore } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { waitForPersist } from '@/lib/persistHydration'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'
import { displayTitle } from '@/model/adapters/text'
import type { SnoozeChoice } from '@/model/types'

import { cancelSnoozeReminder, scheduleSnoozeReminder } from './reminders'
import { type SnoozeEntry, snoozeKey } from './snoozeEntries'
import { NO_SNOOZES, useSnoozeStore } from './snoozeStore'
import { snoozeLabels } from './snoozeTimes'

let cleanupGeneration = 0

async function cancelReminders(entries: SnoozeEntry[]): Promise<void> {
    await Promise.allSettled(
        entries.map((entry) => (entry.kind === 'until' ? cancelSnoozeReminder(entry.notificationId) : undefined))
    )
}

// A snooze that is still being saved belongs to the session that left, so it must not land after a switch.
addSessionEndTask(() => {
    cleanupGeneration += 1
})

// Snoozes and their reminders belong to the account that made them. Another account on this device keeps its own.
addAccountRemovedTask(async (account) => {
    await cancelReminders(useSnoozeStore.getState().removeAccount(account.key))
})

void Promise.all([launchAccount(), waitForPersist(useSnoozeStore)]).then(([account]) =>
    cancelReminders(useSnoozeStore.getState().adoptLegacy(account))
)

export function useSnoozeEntries(): Record<string, SnoozeEntry> {
    const account = useAuthStore((state) => state.activeAccountKey)
    return useSnoozeStore((state) => (account ? state.accounts[account] : undefined) ?? NO_SNOOZES)
}

/** Ends a time snooze and cancels its reminder. Signal snoozes stay: the server decides when they end. */
export async function wakeSnooze(scope: ProjectScope, reportId: string): Promise<void> {
    const account = useAuthStore.getState().activeAccountKey
    if (!account) {
        return
    }
    const key = snoozeKey(scope, reportId)
    const entry = useSnoozeStore.getState().accounts[account]?.[key]
    if (entry?.kind !== 'until') {
        return
    }
    useSnoozeStore.getState().take(account, key)
    await cancelSnoozeReminder(entry.notificationId)
}

function cachedTitle(queryClient: QueryClient, scope: ProjectScope, reportId: string): string {
    const report = queryClient.getQueryData<SignalReportApi>(reportKeys.detail(scope, reportId))
    const list = queryClient.getQueryData<InfiniteData<InboxPageApi, number>>(reportKeys.inbox(scope))
    const fromList = list?.pages.flatMap((page) => page.results).find((candidate) => candidate.id === reportId)
    return displayTitle(report?.title || fromList?.title, 'Report')
}

interface SnoozeOperation {
    account: string
    isCurrent: () => boolean
}

function currentOperation(scope: ProjectScope): SnoozeOperation | null {
    const session = sessionGeneration()
    const cleanup = cleanupGeneration
    // A report a link opened can belong to another project than the session's, so the check is that the session's
    // project stayed the same during the operation, not that it is the scope's project.
    const { projectId, activeAccountKey: account } = useAuthStore.getState()
    if (!account) {
        return null
    }
    return {
        account,
        isCurrent: () => {
            const auth = useAuthStore.getState()
            return (
                sessionGeneration() === session &&
                cleanupGeneration === cleanup &&
                auth.signedIn &&
                auth.activeAccountKey === account &&
                auth.host?.replace(/\/$/, '') === scope.host &&
                auth.projectId === projectId
            )
        },
    }
}

async function snoozeUntil(
    queryClient: QueryClient,
    scope: ProjectScope,
    reportId: string,
    until: string
): Promise<boolean> {
    const operation = currentOperation(scope)
    if (!operation?.isCurrent()) {
        return false
    }
    const { account, isCurrent } = operation
    const key = snoozeKey(scope, reportId)
    const previous = useSnoozeStore.getState().take(account, key)
    if (previous?.kind === 'until') {
        await cancelSnoozeReminder(previous.notificationId).catch(() => undefined)
    }
    if (!isCurrent()) {
        return false
    }
    const notificationId = await scheduleSnoozeReminder(
        {
            reportId,
            projectId: scope.projectId,
            title: cachedTitle(queryClient, scope, reportId),
            until,
        },
        isCurrent
    ).catch(() => undefined)
    if (!isCurrent()) {
        await cancelSnoozeReminder(notificationId)
        return false
    }
    useSnoozeStore.getState().put(account, key, {
        kind: 'until',
        until,
        at: new Date().toISOString(),
        ...(notificationId ? { notificationId } : {}),
    })
    return true
}

async function snoozeForSignals(scope: ProjectScope, reportId: string, count: number): Promise<boolean> {
    const operation = currentOperation(scope)
    if (!operation?.isCurrent()) {
        return false
    }
    const { account, isCurrent } = operation
    const report = await snoozeReportForSignals(scope, reportId, count)
    if (!isCurrent()) {
        return false
    }
    const key = snoozeKey(scope, reportId)
    const previous = useSnoozeStore.getState().take(account, key)
    if (previous?.kind === 'until') {
        await cancelSnoozeReminder(previous.notificationId).catch(() => undefined)
    }
    if (!isCurrent()) {
        return false
    }
    useSnoozeStore.getState().put(account, key, {
        kind: 'signals',
        threshold: typeof report.signals_at_run === 'number' ? report.signals_at_run : null,
        at: new Date().toISOString(),
    })
    return true
}

export function useSnoozeAction(reportId: string): AsyncAction<[SnoozeChoice]> {
    const demo = useDemoMode((state) => state.enabled)
    const demoSnooze = useDemoMode((state) => state.snooze)
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    return useAsyncAction(async (choice: SnoozeChoice) => {
        if (demo) {
            demoSnooze(reportId, snoozeLabels(choice, new Date()))
            return
        }
        if (!scope) {
            throw new NotSignedInError()
        }
        if (choice.kind === 'signals') {
            if (!(await snoozeForSignals(scope, reportId, choice.count))) {
                return
            }
            void queryClient.invalidateQueries({ queryKey: reportKeys.report(scope, reportId) })
            void queryClient.invalidateQueries({ queryKey: reportKeys.inbox(scope) })
        } else {
            if (!(await snoozeUntil(queryClient, scope, reportId, choice.until))) {
                return
            }
        }
        track('mobile_report_snoozed', { kind: choice.kind, preset: choice.kind === 'until' ? choice.preset : null })
    })
}
