import { useActions, useValues } from 'kea'

import { DateRangePickerWithZoom } from 'lib/components/DateFilter/DateRangePicker'

import { DateRange } from '~/queries/schema/schema-general'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { logsViewerSettingsLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerSettingsLogic'

export interface LogsDateRangePickerProps {
    dateRange: DateRange
    setDateRange: (dateRange: DateRange) => void
}

export const LogsDateRangePicker = ({ dateRange, setDateRange }: LogsDateRangePickerProps): JSX.Element => {
    const { timezone } = useValues(logsViewerSettingsLogic)
    const { setTimezone } = useActions(logsViewerSettingsLogic)
    // Route zoom through the logic action so it captures analytics and reloads dependent views (histogram, patterns).
    const { zoomDateRange } = useActions(logsViewerFiltersLogic)

    return (
        <DateRangePickerWithZoom
            logicKey="logs"
            dateRange={dateRange}
            setDateRange={setDateRange}
            timezone={timezone}
            onTimezoneChange={setTimezone}
            onZoom={zoomDateRange}
        />
    )
}
