import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { METRICS_DATE_RANGES, transactionalEmailMetricsLogic } from './transactionalEmailMetricsLogic'

const DATA_ATTR = 'transactional-email-metrics-date-filter'

export function TransactionalEmailMetricsDateRange(): JSX.Element {
    const { hours } = useValues(transactionalEmailMetricsLogic)
    const { setHours } = useActions(transactionalEmailMetricsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!todayRailNav) {
        return (
            <LemonSelect
                size="small"
                value={hours}
                onChange={setHours}
                options={METRICS_DATE_RANGES.map((range) => ({ value: range.value, label: range.label }))}
                data-attr={DATA_ATTR}
            />
        )
    }

    return (
        <Select<number> value={hours} onValueChange={(value) => value !== null && setHours(value)}>
            <SelectTrigger render={<Button variant="outline" left />} data-attr={DATA_ATTR}>
                <SelectValue>
                    {(value: number) => METRICS_DATE_RANGES.find((range) => range.value === value)?.label}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="end" alignItemWithTrigger={false}>
                {METRICS_DATE_RANGES.map((range) => (
                    <SelectItem key={range.value} value={range.value}>
                        {range.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
