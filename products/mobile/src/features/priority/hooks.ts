import { useQueryClient } from '@tanstack/react-query'

import { NotSignedInError } from '@/api/client'
import { postPriorityJudgment, reportKeys } from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDemoMode } from '@/demo/demoMode'
import { actionTracker } from '@/lib/analytics'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'
import type { ReportPriority } from '@/model/types'

export function useSetPriorityAction(reportId: string): AsyncAction<[ReportPriority]> {
    const demo = useDemoMode((state) => state.enabled)
    const demoSetPriority = useDemoMode((state) => state.setPriority)
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    return useAsyncAction(async (priority: ReportPriority) => {
        const record = actionTracker({ report_id: reportId, priority })
        if (demo) {
            demoSetPriority(reportId, priority)
            record('mobile_report_priority_changed')
            return
        }
        if (!scope) {
            throw new NotSignedInError()
        }
        try {
            await postPriorityJudgment(reportId, priority, record.actionId)
            record('mobile_report_priority_changed')
        } catch (error) {
            record('mobile_report_action_failed', { action: 'priority' })
            throw error
        }
        // The fallback inbox list sorts by priority.
        void queryClient.invalidateQueries({ queryKey: reportKeys.inbox(scope) })
        void queryClient.invalidateQueries({ queryKey: reportKeys.artefacts(scope, reportId) })
        // The sheet closes when this resolves, so wait for the report that carries the new priority.
        await queryClient.invalidateQueries({ queryKey: reportKeys.detail(scope, reportId) })
    })
}
