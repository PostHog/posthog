import { IconCheck } from '@posthog/icons'
import { Dot, TabsList, TabsTrigger } from '@posthog/quill'

import { SignalReport } from '../../../types'
import { REPORT_STAGE_LABEL, ReportStage, reportStageProgress } from './reportStages'

/** Each tab also shows how far the report's work has come: a check for a finished stage, a dot for the current one. */
export function ReportStageTabs({ report, stages }: { report: SignalReport; stages: ReportStage[] }): JSX.Element {
    return (
        <TabsList aria-label="Report stage">
            {stages.map((stage) => {
                const progress = reportStageProgress(stage, report)
                return (
                    <TabsTrigger key={stage} value={stage} data-attr={`inbox-report-stage-${stage}`}>
                        {progress === 'done' && <IconCheck aria-hidden />}
                        {progress === 'current' && <Dot variant="info" aria-hidden />}
                        <span>{REPORT_STAGE_LABEL[stage]}</span>
                        {progress !== 'upcoming' && (
                            <span className="sr-only">{progress === 'done' ? '(done)' : '(current stage)'}</span>
                        )}
                    </TabsTrigger>
                )
            })}
        </TabsList>
    )
}
