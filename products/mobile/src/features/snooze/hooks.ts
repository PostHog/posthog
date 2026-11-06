import { type InfiniteData, type QueryClient, useQueryClient } from '@tanstack/react-query'

import { NotSignedInError } from '@/api/client'
import {
    type InboxPageApi,
    type ProjectScope,
    reportKeys,
    type SignalReportApi,
    snoozeReportForSignals,
} from '@/api/reports'
import { addSessionEndTask, useAuthStore } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'
import { displayTitle } from '@/model/adapters/text'
import type { SnoozeChoice } from '@/model/types'

import { cancelSnoozeReminder, scheduleSnoozeReminder } from './reminders'
import { type SnoozeEntry, snoozeKey } from './snoozeEntries'
import { useSnoozeStore } from './snoozeStore'
import { snoozeLabels } from './snoozeTimes'

let cleanupGeneration = 0

// Snoozes and their reminders belong to the user who made them, so the next user on this device starts clean.
addSessionEndTask(async () => {
    cleanupGeneration += 1
    const removed = useSnoozeStore.getState().clear()
    await Promise.allSettled(
        removed.map((entry) => (entry.kind === 'until' ? cancelSnoozeReminder(entry.notificationId) : undefined))
    )
})

export function useSnoozeEntries(): Record<string, SnoozeEntry> {
    return useSnoozeStore((state) => state.entries)
}

/** Ends a time snooze and cancels its reminder. Signal snoozes stay: the server decides when they end. */
export async function wakeSnooze(scope: ProjectScope, reportId: string): Promise<void> {
    const key = snoozeKey(scope, reportId)
    const entry = useSnoozeStore.getState().entries[key]
    if (entry?.kind !== 'until') {
        return
    }
    useSnoozeStore.getState().take(key)
    await cancelSnoozeReminder(entry.notificationId)
}

function cachedTitle(queryClient: QueryClient, scope: ProjectScope, reportId: string): string {
    const report = queryClient.getQueryData<SignalReportApi>(reportKeys.detail(scope, reportId))
    const list = queryClient.getQueryData<InfiniteData<InboxPageApi, number>>(reportKeys.inbox(scope))
    const fromList = list?.pages.flatMap((page) => page.results).find((candidate) => candidate.id === reportId)
    return displayTitle(report?.title || fromList?.title, 'Report')
}

function currentOperation(scope: ProjectScope): () => boolean {
    const session = sessionGeneration()
    const cleanup = cleanupGeneration
    return () => {
        const auth = useAuthStore.getState()
        return (
            sessionGeneration() === session &&
            cleanupGeneration === cleanup &&
            auth.signedIn &&
            auth.host?.replace(/\/$/, '') === scope.host &&
            auth.projectId === scope.projectId
        )
    }
}

async function snoozeUntil(
    queryClient: QueryClient,
    scope: ProjectScope,
    reportId: string,
    until: string
): Promise<boolean> {
    const isCurrent = currentOperation(scope)
    if (!isCurrent()) {
        return false
    }
    const key = snoozeKey(scope, reportId)
    const previous = useSnoozeStore.getState().take(key)
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
    useSnoozeStore.getState().put(key, {
        kind: 'until',
        until,
        at: new Date().toISOString(),
        ...(notificationId ? { notificationId } : {}),
    })
    return true
}

async function snoozeForSignals(scope: ProjectScope, reportId: string, count: number): Promise<boolean> {
    const isCurrent = currentOperation(scope)
    if (!isCurrent()) {
        return false
    }
    const report = await snoozeReportForSignals(reportId, count)
    if (!isCurrent()) {
        return false
    }
    const key = snoozeKey(scope, reportId)
    const previous = useSnoozeStore.getState().take(key)
    if (previous?.kind === 'until') {
        await cancelSnoozeReminder(previous.notificationId).catch(() => undefined)
    }
    if (!isCurrent()) {
        return false
    }
    useSnoozeStore.getState().put(key, {
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
