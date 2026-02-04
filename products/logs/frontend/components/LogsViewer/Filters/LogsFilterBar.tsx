import { useActions, useValues } from 'kea'

import { IconMinusSquare, IconPlusSquare, IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconPauseCircle, IconPlayCircle } from 'lib/lemon-ui/icons'
import { Scene } from 'scenes/sceneTypes'

import { logsSceneLogic } from '../../../logsSceneLogic'
import { DateRangeFilter } from './DateRangeFilter'
import { LogsFilterGroup } from './FilterGroup'
import { FilterHistoryDropdown } from './FilterHistoryDropdown'
import { LogsDateRangePicker } from './LogsDateRangePicker/LogsDateRangePicker'
import { ServiceFilter } from './ServiceFilter'
import { SeverityLevelsFilter } from './SeverityLevelsFilter'

export const LogsFilterBar = (): JSX.Element => {
    const newLogsDateRangePicker = useFeatureFlag('NEW_LOGS_DATE_RANGE_PICKER')
    const { logsLoading, liveTailRunning, liveTailDisabledReason, dateRange } = useValues(logsSceneLogic)
    const { runQuery, zoomDateRange, setLiveTailRunning, setDateRange } = useActions(logsSceneLogic)

    return (
        <div className="flex flex-col gap-y-1.5">
            <div className="flex justify-between gap-y-2 flex-wrap-reverse">
                <div className="flex gap-x-1 gap-y-2 flex-wrap">
                    <SeverityLevelsFilter />
                    <ServiceFilter />
                    <FilterHistoryDropdown />
                </div>
                <div className="flex gap-x-1">
                    <LemonButton
                        size="small"
                        icon={<IconMinusSquare />}
                        type="secondary"
                        onClick={() => zoomDateRange(2)}
                    />
                    <LemonButton
                        size="small"
                        icon={<IconPlusSquare />}
                        type="secondary"
                        onClick={() => zoomDateRange(0.5)}
                    />

                    {!newLogsDateRangePicker && <DateRangeFilter />}
                    {newLogsDateRangePicker && (
                        <LogsDateRangePicker dateRange={dateRange} setDateRange={setDateRange} />
                    )}

                    <LemonButton
                        size="small"
                        icon={<IconRefresh />}
                        type="secondary"
                        onClick={() => runQuery()}
                        loading={logsLoading || liveTailRunning}
                        className="min-w-24"
                        disabledReason={liveTailRunning ? 'Disable live tail to manually refresh' : undefined}
                    >
                        {liveTailRunning ? 'Tailing...' : 'Refresh'}
                    </LemonButton>
                    <AppShortcut
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
                    </AppShortcut>
                </div>
            </div>
            <LogsFilterGroup />
        </div>
    )
}
