import { useActions, useValues } from 'kea'

import { IconKeyboard } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { IconPauseCircle, IconPlayCircle } from 'lib/lemon-ui/icons'
import { Scene } from 'scenes/sceneTypes'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { LogsOrderBy } from 'products/logs/frontend/types'

import { logsViewerDataLogic } from './data/logsViewerDataLogic'
import { LogsExportMenu } from './LogsExportMenu'
import { logsViewerLogic } from './logsViewerLogic'
import { TimezoneSelect } from './TimezoneSelect'

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
    const { wrapBody, timezone } = useValues(logsViewerLogic)
    const { setWrapBody, setTimezone } = useActions(logsViewerLogic)
    const { liveTailRunning, liveTailDisabledReason } = useValues(logsViewerDataLogic)
    const { setLiveTailRunning } = useActions(logsViewerDataLogic)

    return (
        <div className="flex items-center gap-2 flex-wrap">
            <Shortcut
                name="LogsLiveTail"
                keybind={[keyBinds.edit]}
                intent={liveTailRunning ? 'Stop live tail' : 'Start live tail'}
                interaction="click"
                scope={Scene.Logs}
            >
                <LemonButton
                    size="small"
                    type={liveTailRunning ? 'primary' : 'secondary'}
                    icon={liveTailRunning ? <IconPauseCircle /> : <IconPlayCircle />}
                    onClick={() => setLiveTailRunning(!liveTailRunning)}
                    disabledReason={liveTailRunning ? undefined : liveTailDisabledReason}
                >
                    Live tail
                </LemonButton>
            </Shortcut>
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
    )
}
