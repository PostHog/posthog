import { useActions, useValues } from 'kea'

import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'

import { logsExportLogic } from './logsExportLogic'
import { logsViewerLogic } from './logsViewerLogic'

interface LogsExportMenuProps {
    totalLogsCount?: number
}

export const LogsExportMenu = ({ totalLogsCount }: LogsExportMenuProps): JSX.Element => {
    const { selectedCount } = useValues(logsViewerLogic)
    const { exportServerSide, exportSelectedAsCsv, copySelectedLogs } = useActions(logsExportLogic)
    const { maxExportableLogs } = useValues(logsExportLogic)

    return (
        <LemonMenu
            items={[
                ...(selectedCount > 0
                    ? [
                          {
                              title: `Selected logs (${humanFriendlyNumber(selectedCount)})`,
                              items: [
                                  { label: 'Copy to clipboard', onClick: copySelectedLogs },
                                  { label: 'Export as CSV', onClick: exportSelectedAsCsv },
                              ],
                          },
                      ]
                    : []),
                {
                    title: totalLogsCount
                        ? `All matching logs (${humanFriendlyNumber(totalLogsCount)})`
                        : 'All matching logs',
                    items: [
                        {
                            label: 'Export as CSV',
                            onClick: () => exportServerSide(totalLogsCount),
                            disabledReason:
                                totalLogsCount && totalLogsCount > maxExportableLogs
                                    ? `Too many logs (${humanFriendlyNumber(totalLogsCount)}). Narrow your filters to under ${humanFriendlyNumber(maxExportableLogs)}.`
                                    : undefined,
                        },
                    ],
                },
            ]}
        >
            <LemonButton size="small" type="secondary" icon={<IconDownload />} tooltip="Export logs" />
        </LemonMenu>
    )
}
