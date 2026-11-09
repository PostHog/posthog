import { useQueryClient } from '@tanstack/react-query'

import { NotSignedInError } from '@/api/client'
import { postPriorityJudgment, reportKeys } from '@/api/reports'
import { sessionGeneration } from '@/auth/tokens'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDemoMode } from '@/demo/demoMode'
import { reportScopeError } from '@/features/views/useViewsAccess'
import { track } from '@/lib/analytics'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'
import type { ReportPriority } from '@/model/types'

export function useSetPriorityAction(reportId: string): AsyncAction<[ReportPriority]> {
    const demo = useDemoMode((state) => state.enabled)
    const demoSetPriority = useDemoMode((state) => state.setPriority)
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    return useAsyncAction(async (priority: ReportPriority) => {
        if (demo) {
            demoSetPriority(reportId, priority)
            return
        }
        if (!scope) {
            throw new NotSignedInError()
        }
        const session = sessionGeneration()
        try {
            await postPriorityJudgment(scope, reportId, priority)
        } catch (error) {
            if (sessionGeneration() === session) {
                reportScopeError(error, 'inbox')
            }
            throw error
        }
        track('mobile_report_priority_changed', { report_id: reportId, priority })
        // The fallback inbox list sorts by priority.
        void queryClient.invalidateQueries({ queryKey: reportKeys.inbox(scope) })
        void queryClient.invalidateQueries({ queryKey: reportKeys.artefacts(scope, reportId) })
        // The sheet closes when this resolves, so wait for the report that carries the new priority.
        await queryClient.invalidateQueries({ queryKey: reportKeys.detail(scope, reportId) })
    })
}
