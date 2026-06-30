import { useActions, useValues } from 'kea'

import { IconKeyboard } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { TimezoneSelect } from 'lib/components/TimezoneSelect'
import { IconPauseCircle, IconPlayCircle } from 'lib/lemon-ui/icons'
import { Scene } from 'scenes/sceneTypes'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { logsViewerDataLogic } from 'products/logs/frontend/components/LogsViewer/data/logsViewerDataLogic'
import { LogsOrderBy } from 'products/logs/frontend/types'

import { LogsExportMenu } from './LogsExportMenu'
import { logsViewerLogic } from './logsViewerLogic'

export interface LogsViewerToolbarProps {
    // Used by the export menu for its "all matching logs" label + size limit, not shown as a count here
    // (the lens-aware count indicator lives in the results bar's persistent-left frame).
    totalLogsCount?: number
    orderBy: LogsOrderBy
    onChangeOrderBy: (orderBy: LogsOrderBy) => void
}

/**
 * Contextual-right cluster of the results bar — live tail plus how the Logs list renders (sort, wrap,
 * timezone, export) and the keyboard-shortcut help. Logs-only: the bar hides this whole cluster in
 * Patterns mode, where none of it applies. Live tail streams the query (the others don't re-run it) —
 * it lives here, technically the "wrong" scope, so it hides with this cluster instead of shifting the
 * top bar's layout when the lens changes.
 */
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
