import { useMemo } from 'react'

import { useDataMode } from '@/demo/demoMode'
import type { QueryState, ReportView } from '@/model/types'

import { useReport } from '../report/hooks'
import { useHandoffEntry } from './hooks'
import { mergeLiveRun, runTarget } from './liveReport'
import { useTaskRun } from './useTaskRun'

// Lives outside `hooks.ts` because `report/hooks.ts` imports the hand-off actions from there.
export function useReportWithLiveRun(reportId: string): QueryState<ReportView> {
    const query = useReport(reportId)
    const live = useDataMode() === 'live'
    const entry = useHandoffEntry(reportId)
    const report = query.data
    useTaskRun(reportId, live ? runTarget(report, entry) : undefined, live && report !== undefined)
    const data = useMemo(() => (live && report ? mergeLiveRun(report, entry) : report), [live, report, entry])
    return data === report ? query : { ...query, data }
}
