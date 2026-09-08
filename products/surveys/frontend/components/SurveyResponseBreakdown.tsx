import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import type { SurveyResponseOutcome } from 'scenes/surveys/utils'

export function SurveyResponseBreakdown({ outcomes }: { outcomes: SurveyResponseOutcome[] }): JSX.Element {
    return (
        <Tooltip title="Percentages are of all responses matching the current filters. Each submission counts once. Dismissed and abandoned responses contain partial answers.">
            <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-xs">
                <span className="text-secondary">Of responses:</span>
                {outcomes.map((outcome) => (
                    <span key={outcome.label} className="inline-flex items-center gap-1 whitespace-nowrap">
                        <LemonTag type={outcome.label === 'Completed' ? 'success' : 'warning'}>
                            {outcome.label}
                        </LemonTag>
                        <span className="tabular-nums">
                            {humanFriendlyNumber(outcome.count)} ({percentage(outcome.percentage, 1)})
                        </span>
                    </span>
                ))}
            </div>
        </Tooltip>
    )
}
