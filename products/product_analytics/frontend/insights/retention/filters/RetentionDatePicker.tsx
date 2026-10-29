import { useActions, useValues } from 'kea'

import { IconCalendar, IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { type DateFilterExclusions } from 'lib/components/DateFilter/DateFilterExclusionsControl'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { NodeKind } from '~/queries/schema/schema-general'

import { retentionLogic } from '../retentionLogic'

export function RetentionDatePicker(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { dateRange, dateMappings, retentionFilter } = useValues(retentionLogic(insightProps))
    const { updateDateRange } = useActions(retentionLogic(insightProps))
    const { reportInsightDateExclusionsChanged } = useActions(eventUsageLogic)

    const exclusions: DateFilterExclusions = { days: [], incomplete: !!dateRange?.excludeIncompletePeriods }

    return (
        <DateFilter
            dateTo={dateRange?.date_to ?? undefined}
            dateFrom={dateRange?.date_from ?? undefined}
            onChange={(date_from, date_to, explicit_date) => {
                updateDateRange({ date_from, date_to, explicitDate: explicit_date })
            }}
            dateOptions={dateMappings}
            exclusions={exclusions}
            onExclusionsChange={({ incomplete }) => {
                if (incomplete !== exclusions.incomplete) {
                    updateDateRange({ excludeIncompletePeriods: incomplete ? true : null }, true)
                    reportInsightDateExclusionsChanged(NodeKind.RetentionQuery, incomplete, 0)
                }
            }}
            showIncompletePeriodExclusion={retentionFilter?.timeWindowMode !== '24_hour_windows'}
            makeLabel={(key) => (
                <>
                    <IconCalendar /> {key}
                    {key == 'All time' && (
                        <Tooltip title="Only events dated after 2015 will be shown">
                            <IconInfo className="info-indicator" />
                        </Tooltip>
                    )}
                </>
            )}
            disabledReason={editingDisabledReason}
        />
    )
}
