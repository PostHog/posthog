import { useActions, useValues } from 'kea'

import { IconExpand45 } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSegmentedButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { LogsColumnsModal } from 'products/logs/frontend/components/LogsViewer/LogsColumnsModal/LogsColumnsModal'
import { LogsOrderBy } from 'products/logs/frontend/types'

import { LogsExportMenu } from './LogsExportMenu'
import { logsViewerLogic } from './logsViewerLogic'
import { TimezoneSelect } from './TimezoneSelect'

export interface LogsViewerToolbarProps {
    viewerId: string
    totalLogsCount?: number
    orderBy: LogsOrderBy
    onChangeOrderBy: (orderBy: LogsOrderBy) => void
    onOpenFullScreen?: () => void
}

export const LogsViewerToolbar = ({
    viewerId,
    totalLogsCount,
    orderBy,
    onChangeOrderBy,
    onOpenFullScreen,
}: LogsViewerToolbarProps): JSX.Element => {
    const { wrapBody, timezone } = useValues(logsViewerLogic)
    const { setWrapBody, setTimezone } = useActions(logsViewerLogic)

    return (
        <div className="flex justify-between flex-wrap gap-2">
            <div className="flex gap-2 flex-wrap">
                <LemonSegmentedButton
                    value={orderBy}
                    onChange={onChangeOrderBy}
                    options={[
                        {
                            value: 'earliest',
                            label: 'Earliest',
                        },
                        {
                            value: 'latest',
                            label: 'Latest',
                        },
                    ]}
                    size="small"
                />
                <LemonCheckbox checked={wrapBody} bordered onChange={setWrapBody} label="Wrap message" size="small" />
                <TimezoneSelect value={timezone} onChange={setTimezone} size="small" />
                <LogsColumnsModal viewerId={viewerId} />
                <LogsExportMenu totalLogsCount={totalLogsCount} />
                {onOpenFullScreen && (
                    <LemonButton
                        size="small"
                        icon={<IconExpand45 />}
                        onClick={onOpenFullScreen}
                        tooltip="Full screen"
                    />
                )}
            </div>
            <div className="flex items-center gap-4 flex-wrap">
                {totalLogsCount !== undefined && totalLogsCount > 0 && (
                    <span className="text-muted text-xs">{humanFriendlyNumber(totalLogsCount)} logs</span>
                )}
                <span className="text-muted text-xs flex items-center gap-1">
                    <KeyboardShortcut arrowup />
                    <KeyboardShortcut arrowdown />
                    or
                    <KeyboardShortcut j />
                    <KeyboardShortcut k />
                    navigate
                    <span className="mx-1">·</span>
                    <KeyboardShortcut enter />
                    expand
                    <span className="mx-1">·</span>
                    <KeyboardShortcut p />
                    prettify
                    <span className="mx-1">·</span>
                    <KeyboardShortcut r />
                    refresh
                </span>
            </div>
        </div>
    )
}
