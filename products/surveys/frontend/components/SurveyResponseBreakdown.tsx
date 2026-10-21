import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import type { SurveyResponseOutcome } from 'scenes/surveys/utils'

const OUTCOME_LABELS: Record<string, { label: string; description: string }> = {
    Completed: { label: 'Completed', description: 'Finished the survey.' },
    Dismissed: { label: 'Partial · dismissed', description: 'Saved answers before closing the survey.' },
    Abandoned: { label: 'Partial · abandoned', description: 'Saved answers without finishing the survey.' },
}

export function SurveyResponseBreakdown({ outcomes }: { outcomes: SurveyResponseOutcome[] }): JSX.Element {
    return (
        <section
            aria-label="Response completion"
            className="@container/response-completion border-t pt-3 flex flex-col gap-2"
        >
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h4 className="text-sm font-semibold m-0">Response completion</h4>
                <Tooltip title="Each response submission counts once, including submissions with partial answers. The person-counting toggle does not change this breakdown.">
                    <span className="text-xs text-secondary">Of response submissions</span>
                </Tooltip>
            </div>
            <dl className="grid grid-cols-1 @min-[48rem]/response-completion:grid-cols-3 gap-x-6 gap-y-2 m-0">
                {outcomes.map((outcome) => {
                    const content = OUTCOME_LABELS[outcome.label]
                    return (
                        <div
                            key={outcome.label}
                            className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1"
                        >
                            <dt className="flex items-center gap-2 text-secondary">
                                <span
                                    aria-hidden="true"
                                    className={`size-2 shrink-0 rounded-full ${outcome.label === 'Completed' ? 'bg-success' : 'bg-muted'}`}
                                />
                                <Tooltip title={content?.description}>
                                    <span>{content?.label ?? outcome.label}</span>
                                </Tooltip>
                            </dt>
                            <dd className="m-0 tabular-nums whitespace-nowrap">
                                <span className="font-semibold">{humanFriendlyNumber(outcome.count)}</span>{' '}
                                <span className="text-secondary ml-2">{percentage(outcome.percentage, 1)}</span>
                            </dd>
                        </div>
                    )
                })}
            </dl>
        </section>
    )
}
