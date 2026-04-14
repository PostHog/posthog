import { useActions, useMountedLogic, useValues } from 'kea'

import { IconCheck, IconMinus, IconWarning, IconX } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils'

import { EvaluationRun } from '../evaluations/types'
import { generationEvaluationRunsLogic } from '../generationEvaluationRunsLogic'
import { TraceViewMode, llmAnalyticsTraceLogic } from '../llmAnalyticsTraceLogic'

interface EvalSummary {
    latestRun: EvaluationRun
    runCount: number
}

function getEvalSummaries(runs: EvaluationRun[]): EvalSummary[] {
    const byEvalId = new Map<string, EvalSummary>()
    for (const run of runs) {
        const existing = byEvalId.get(run.evaluation_id)
        if (existing) {
            existing.runCount++
        } else {
            byEvalId.set(run.evaluation_id, { latestRun: run, runCount: 1 })
        }
    }
    return Array.from(byEvalId.values())
}

function getEvalStatusIcon(run: EvaluationRun): { icon: JSX.Element; label: string } {
    if (run.status === 'failed') {
        return { icon: <IconWarning className="text-danger" />, label: 'Error' }
    }
    if (run.status === 'running') {
        return { icon: <IconMinus className="text-primary" />, label: 'Running' }
    }
    if (run.result === null) {
        return { icon: <IconMinus className="text-muted" />, label: 'N/A' }
    }
    if (run.result) {
        return { icon: <IconCheck className="text-success" />, label: 'True' }
    }
    return { icon: <IconX className="text-danger" />, label: 'False' }
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
                const { icon, label } = getEvalStatusIcon(summary.latestRun)
                return (
                    <Tooltip key={summary.latestRun.evaluation_id} title={<EvalTooltipContent {...summary} />}>
                        <LemonTag
                            size="small"
                            className="bg-surface-primary cursor-pointer"
                            icon={icon}
                            onClick={() => setViewMode(TraceViewMode.Evals)}
                        >
                            {summary.latestRun.evaluation_name}: {label}
                        </LemonTag>
                    </Tooltip>
                )
            })}
        </div>
    )
}
