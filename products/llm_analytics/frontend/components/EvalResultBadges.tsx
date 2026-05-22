import { useActions, useMountedLogic, useValues } from 'kea'

import { IconCheck, IconMinus, IconWarning, IconX } from '@posthog/icons'
import { LemonSkeleton, LemonTag, LemonTagProps, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils'

import { EvaluationRun } from '../evaluations/types'
import { generationEvaluationRunsLogic } from '../generationEvaluationRunsLogic'
import { TraceViewMode, llmAnalyticsTraceLogic } from '../llmAnalyticsTraceLogic'

export interface EvalSummary {
    latestRun: EvaluationRun
    runCount: number
}

export function getEvalSummaries(runs: EvaluationRun[]): EvalSummary[] {
    const sorted = [...runs].sort((a, b) => dayjs(b.timestamp).valueOf() - dayjs(a.timestamp).valueOf())
    const byEvalId = new Map<string, EvalSummary>()
    for (const run of sorted) {
        const existing = byEvalId.get(run.evaluation_id)
        if (existing) {
            existing.runCount++
        } else {
            byEvalId.set(run.evaluation_id, { latestRun: run, runCount: 1 })
        }
    }
    return Array.from(byEvalId.values())
}

export function getEvalBadgeProps(run: EvaluationRun): {
    type: LemonTagProps['type']
    icon: JSX.Element
    label: string
} {
    if (run.status === 'failed') {
        return { type: 'danger', icon: <IconWarning />, label: 'Error' }
    }
    if (run.status === 'running') {
        return { type: 'primary', icon: <IconMinus />, label: 'Running' }
    }
    if (run.result === null) {
        return { type: 'muted', icon: <IconMinus />, label: 'N/A' }
    }
    if (run.result) {
        return { type: 'success', icon: <IconCheck />, label: 'True' }
    }
    return { type: 'danger', icon: <IconX />, label: 'False' }
}

function EvalTooltipContent({ latestRun, runCount }: EvalSummary): JSX.Element {
    return (
        <div className="max-w-80 space-y-1">
            <div className="font-semibold">{latestRun.evaluation_name}</div>
            <div className="text-xs opacity-75">
                {dayjs(latestRun.timestamp).fromNow()}
                {runCount > 1 && <> &middot; {pluralize(runCount, 'run', 'runs', true)} total</>}
            </div>
            {latestRun.reasoning && <div className="text-sm">{latestRun.reasoning}</div>}
        </div>
    )
}

export function EvalResultBadges({ generationEventId }: { generationEventId: string }): JSX.Element | null {
    const { generationEvaluationRuns, generationEvaluationRunsLoading } = useValues(
        generationEvaluationRunsLogic({ generationEventId })
    )
    const traceLogic = useMountedLogic(llmAnalyticsTraceLogic)
    const { setViewMode } = useActions(traceLogic)

    if (generationEvaluationRunsLoading && generationEvaluationRuns.length === 0) {
        return (
            <div className="flex flex-row items-center gap-1.5">
                <LemonSkeleton className="h-5 w-24" />
                <LemonSkeleton className="h-5 w-24" />
            </div>
        )
    }

    const summaries = getEvalSummaries(generationEvaluationRuns)

    if (summaries.length === 0) {
        return null
    }

    return (
        <div className="flex flex-row flex-wrap items-center gap-1.5">
            {summaries.map((summary) => {
                const { type, icon, label } = getEvalBadgeProps(summary.latestRun)
                return (
                    <Tooltip key={summary.latestRun.evaluation_id} title={<EvalTooltipContent {...summary} />}>
                        <LemonTag
                            type={type}
                            size="small"
                            icon={icon}
                            onClick={() => setViewMode(TraceViewMode.Evals)}
                            className="cursor-pointer"
                        >
                            {summary.latestRun.evaluation_name}: {label}
                        </LemonTag>
                    </Tooltip>
                )
            })}
        </div>
    )
}
