import { useQueryClient } from '@tanstack/react-query'

import { NotSignedInError } from '@/api/client'
import { dismissReport, reportKeys, resolveReport } from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDemoMode } from '@/demo/demoMode'
import { type AnalyticsEvent, actionTracker } from '@/lib/analytics'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'
import type { DismissReason, ResolveReason } from '@/model/verdictReasons'

interface VerdictTarget<Reason extends string> {
    send: (reportId: string, reason: Reason, note: string, actionId?: string) => Promise<unknown>
    sendDemo: (reportId: string, reason: Reason) => void
    event: AnalyticsEvent
}

function useVerdictAction<Reason extends string>(
    reportId: string,
    { send, sendDemo, event }: VerdictTarget<Reason>
): AsyncAction<[Reason, string]> {
    const demo = useDemoMode((state) => state.enabled)
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    return useAsyncAction(async (reason: Reason, note: string) => {
        const record = actionTracker({ report_id: reportId, reason, has_note: note.trim().length > 0 })
        if (demo) {
            sendDemo(reportId, reason)
            record(event)
            return
        }
        if (!scope) {
            throw new NotSignedInError()
        }
        try {
            await send(reportId, reason, note, record.actionId)
        } catch (error) {
            record('mobile_report_action_failed', { action: event })
            throw error
        }
        void queryClient.invalidateQueries({ queryKey: reportKeys.report(scope, reportId) })
        void queryClient.invalidateQueries({ queryKey: reportKeys.inbox(scope) })
        // The note is free text the person typed, so only its presence is tracked.
        record(event)
    })
}

export function useResolveAction(reportId: string): AsyncAction<[ResolveReason, string]> {
    const sendDemo = useDemoMode((state) => state.resolve)
    return useVerdictAction(reportId, { send: resolveReport, sendDemo, event: 'mobile_report_resolved' })
}

export function useDismissAction(reportId: string): AsyncAction<[DismissReason, string]> {
    const sendDemo = useDemoMode((state) => state.dismiss)
    return useVerdictAction(reportId, { send: dismissReport, sendDemo, event: 'mobile_report_dismissed' })
}
