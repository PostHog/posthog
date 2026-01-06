import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonSegmentedButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { LogsOrderBy } from 'products/logs/frontend/types'

import { TimezoneSelect } from './TimezoneSelect'
import { logsViewerLogic } from './logsViewerLogic'

export interface LogsViewerToolbarProps {
    totalLogsCount?: number
    orderBy: LogsOrderBy
    onChangeOrderBy: (orderBy: LogsOrderBy) => void
}

export const LogsViewerToolbar = ({
    totalLogsCount,
    orderBy,
    onChangeOrderBy,
}: LogsViewerToolbarProps): JSX.Element => {
    const { wrapBody, prettifyJson, logsCount, timezone } = useValues(logsViewerLogic)
    const { setWrapBody, setPrettifyJson, setTimezone } = useActions(logsViewerLogic)

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
                <LemonCheckbox
                    checked={prettifyJson}
                    bordered
                    onChange={setPrettifyJson}
                    label="Prettify JSON"
                    size="small"
                />
                <TimezoneSelect value={timezone} onChange={setTimezone} size="small" />
            </div>
            <div className="flex items-center gap-4 flex-wrap">
                {totalLogsCount !== undefined && totalLogsCount > 0 && (
                    <span className="text-muted text-xs">
                        {humanFriendlyNumber(logsCount)} of {humanFriendlyNumber(totalLogsCount)} logs
                    </span>
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
