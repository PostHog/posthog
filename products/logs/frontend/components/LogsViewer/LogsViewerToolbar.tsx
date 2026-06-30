import { useActions, useValues } from 'kea'

import { IconExpand45, IconKeyboard } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { TimezoneSelect } from 'lib/components/TimezoneSelect'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { LogsOrderBy } from 'products/logs/frontend/types'

import { LogsExportMenu } from './LogsExportMenu'
import { logsViewerLogic } from './logsViewerLogic'

export interface LogsViewerToolbarProps {
    totalLogsCount?: number
    orderBy: LogsOrderBy
    onChangeOrderBy: (orderBy: LogsOrderBy) => void
    onOpenFullScreen?: () => void
}

export const LogsViewerToolbar = ({
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
                <Tooltip
                    title={
                        <div className="flex flex-col gap-1.5 p-1">
                            <div className="flex items-center justify-between gap-4">
                                <span>Navigate</span>
                                <span className="flex items-center gap-1">
                                    <KeyboardShortcut arrowup />
                                    <KeyboardShortcut arrowdown />
                                    or
                                    <KeyboardShortcut j />
                                    <KeyboardShortcut k />
                                </span>
                            </div>
                            <div className="flex items-center justify-between gap-4">
                                <span>Expand</span>
                                <KeyboardShortcut enter />
                            </div>
                            <div className="flex items-center justify-between gap-4">
                                <span>Prettify</span>
                                <KeyboardShortcut p />
                            </div>
                            <div className="flex items-center justify-between gap-4">
                                <span>Refresh</span>
                                <KeyboardShortcut r />
                            </div>
                        </div>
                    }
                >
                    <button
                        type="button"
                        className="text-muted text-xs flex items-center gap-1 cursor-help bg-transparent border-none p-0"
                        aria-label="Keyboard shortcuts"
                    >
                        <IconKeyboard className="text-base" />
                        Shortcuts
                    </button>
                </Tooltip>
            </div>
        </div>
    )
}
