import { LemonTable, LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import type { SurveyResponseOutcome } from 'scenes/surveys/utils'

export function SurveyResponseBreakdown({ outcomes }: { outcomes: SurveyResponseOutcome[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <h4 className="mb-0">Response outcomes</h4>
            <p className="text-xs text-secondary mb-0">
                Each submission counts once. Dismissed and abandoned responses contain partial answers.
            </p>
            <LemonTable
                size="small"
                rowKey="label"
                dataSource={outcomes}
                columns={[
                    {
                        title: 'Outcome',
                        dataIndex: 'label',
                        render: (_, outcome) => (
                            <LemonTag type={outcome.label === 'Completed' ? 'success' : 'warning'}>
                                {outcome.label}
                            </LemonTag>
                        ),
                    },
                    {
                        title: 'Responses',
                        dataIndex: 'count',
                        align: 'right',
                        render: (_, outcome) => humanFriendlyNumber(outcome.count),
                    },
                    {
                        title: '% of responses',
                        dataIndex: 'percentage',
                        align: 'right',
                        render: (_, outcome) => percentage(outcome.percentage, 1),
                    },
                ]}
            />
        </div>
    )
}
