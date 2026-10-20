import { useActions, useValues } from 'kea'

import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { RetentionFilter } from '~/queries/schema/schema-general'

export function QuillRetentionTimeWindowModePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <QuillSelect<NonNullable<RetentionFilter['timeWindowMode']>>
            value={retentionFilter?.timeWindowMode ?? 'strict_calendar_dates'}
            onChange={(timeWindowMode) => updateInsightFilter({ timeWindowMode })}
            options={[
                {
                    value: 'strict_calendar_dates',
                    label: 'strict calendar intervals',
                    description: 'Intervals are based on calendar boundaries (e.g., midnight for daily retention)',
                },
                {
                    value: '24_hour_windows',
                    label: 'rolling 24-hour windows',
                    description:
                        "Intervals are calculated from each user's first event timestamp (e.g., if a user starts at 11 PM, their 'next day' is 24 hours later at 11 PM)",
                },
            ]}
        />
    )
}
