import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { DateRangePickerWithZoom } from 'lib/components/DateFilter/DateRangePicker'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'

import { DateRange } from '~/queries/schema/schema-general'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { logsViewerSettingsLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerSettingsLogic'
import { logsRetentionSettingsUrl } from 'products/logs/frontend/logsRetentionSettingsUrl'
import {
    LOGS_RETENTION_DATE_FORMAT,
    logsRangeBeyondRetention,
    logsRetentionWindowStart,
    resolveLogsRetentionDays,
} from 'products/logs/frontend/logsRetentionWindow'

export interface LogsDateRangePickerProps {
    dateRange: DateRange
    setDateRange: (dateRange: DateRange) => void
}

export const LogsDateRangePicker = ({ dateRange, setDateRange }: LogsDateRangePickerProps): JSX.Element => {
    const { timezone } = useValues(logsViewerSettingsLogic)
    const { setTimezone } = useActions(logsViewerSettingsLogic)
    // Route zoom through the logic action so it captures analytics and reloads dependent views (histogram, patterns).
    const { zoomDateRange } = useActions(logsViewerFiltersLogic)
    const { currentTeam } = useValues(teamLogic)

    const retentionDays = resolveLogsRetentionDays(currentTeam?.logs_settings)
    const windowStart = logsRetentionWindowStart(retentionDays, timezone).format(LOGS_RETENTION_DATE_FORMAT)
    const beyondRetention = logsRangeBeyondRetention(dateRange, retentionDays, timezone)

    return (
        <>
            <DateRangePickerWithZoom
                logicKey="logs"
                dateRange={dateRange}
                setDateRange={setDateRange}
                timezone={timezone}
                onTimezoneChange={setTimezone}
                onZoom={zoomDateRange}
                dataAvailabilityNotice={({ closePicker }) => (
                    <>
                        Your logs are kept for <span translate="no">{retentionDays}</span> days by default, back to{' '}
                        <span translate="no">{windowStart}</span>. Older logs have been deleted. Retention rules can
                        keep matching logs longer or delete them sooner.{' '}
                        <Link
                            to={logsRetentionSettingsUrl()}
                            data-attr="logs-date-picker-retention"
                            onClick={closePicker}
                        >
                            Change retention
                        </Link>
                    </>
                )}
            />
            {beyondRetention && (
                <Tooltip
                    title={`This range starts before ${windowStart}, which is outside your default log retention of ${retentionDays} days. Logs from before then have been deleted. Retention rules can keep matching logs longer or delete them sooner.`}
                >
                    <IconWarning className="text-warning self-center text-base" data-attr="logs-retention-warning" />
                </Tooltip>
            )}
        </>
    )
}
