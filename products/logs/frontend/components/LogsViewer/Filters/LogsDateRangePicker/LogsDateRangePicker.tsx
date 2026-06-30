import { useActions, useValues } from 'kea'

import { DateRangePicker } from 'lib/components/DateFilter/DateRangePicker'

import { DateRange } from '~/queries/schema/schema-general'

import { logsViewerSettingsLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerSettingsLogic'

export interface LogsDateRangePickerProps {
    dateRange: DateRange
    setDateRange: (dateRange: DateRange) => void
}

export const LogsDateRangePicker = ({ dateRange, setDateRange }: LogsDateRangePickerProps): JSX.Element => {
    const { timezone } = useValues(logsViewerSettingsLogic)
    const { setTimezone } = useActions(logsViewerSettingsLogic)

    return (
        <DateRangePicker
            logicKey="logs"
            dateRange={dateRange}
            setDateRange={setDateRange}
            timezone={timezone}
            onTimezoneChange={setTimezone}
        />
    )
}
